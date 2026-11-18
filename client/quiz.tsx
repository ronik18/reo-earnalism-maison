import { useEffect, useRef, useState, type FormEvent } from "react";
import { mountIsland } from "./lifecycle";
import { api, errorText, readBootstrap, t, locale } from "./api";
interface Quiz {
  quiz_id: string;
  lesson_id: string;
  version: number;
  questions: {
    question_id: string;
    prompt: string;
    kind: string;
    options: { option_id: string; text: string }[];
  }[];
}
interface Attempt {
  attempt_id: string;
  version: number;
}
interface Result {
  score: number;
  result: { question_id: string; correct: boolean; explanation: string }[];
}
function QuizIsland({ quiz }: { quiz: Quiz }) {
  const draftKey = "maison.quiz:" + (document.body.dataset.memberId || "guest") + ":" + quiz.quiz_id + ":" + quiz.version;
  const [answers, setAnswers] = useState<Record<string, string>>(() => {
    try {
      const saved = JSON.parse(sessionStorage.getItem(draftKey) || "{}");
      return Object.fromEntries(quiz.questions.filter(q=>q.options.some(o=>o.option_id===saved[q.question_id])).map(q=>[q.question_id,saved[q.question_id]]));
    } catch { return {}; }
  });
  const [online,setOnline]=useState(navigator.onLine);
  const [draftFailed,setDraftFailed]=useState(false);
  useEffect(()=>{const update=()=>setOnline(navigator.onLine);window.addEventListener("online",update);window.addEventListener("offline",update);return()=>{window.removeEventListener("online",update);window.removeEventListener("offline",update);};},[]);
  useEffect(()=>{try {sessionStorage.setItem(draftKey,JSON.stringify(answers));} catch {setDraftFailed(true);}},[draftKey,answers]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Result>();
  const attempt = useRef<Attempt | undefined>(undefined);
  const startKey = useRef(crypto.randomUUID());
  const submission = useRef<
    | { key: string; answers: { question_id: string; option_id: string }[] }
    | undefined
  >(undefined);
  const output = useRef<HTMLDivElement>(null);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (busy || result) return;
    if (!navigator.onLine) {setError(t("quiz_draft_pending"));return;}
    if (quiz.questions.some((q) => !answers[q.question_id])) {
      setError(t("invalid_input"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      attempt.current ??= await api<Attempt>(
        `/learning/quizzes/${quiz.quiz_id}/attempts`,
        {
          method: "POST",
          key: startKey.current,
          body: { quiz_version: quiz.version },
        },
      );
      submission.current ??= {
        key: crypto.randomUUID(),
        answers: quiz.questions.map((q) => ({
          question_id: q.question_id,
          option_id: answers[q.question_id],
        })),
      };
      setResult(
        await api<Result>(
          `/learning/attempts/${attempt.current.attempt_id}/submit`,
          {
            method: "POST",
            key: submission.current.key,
            version: attempt.current.version,
            body: { answers: submission.current.answers },
          },
        ),
      );
      try {sessionStorage.removeItem(draftKey);} catch { /* Server result remains authoritative. */ }
      requestAnimationFrame(() => output.current?.focus());
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  if (quiz.questions.some((q) => q.kind !== "single_choice"))
    return <p className="notice">{t("not_available")}</p>;
  return (
    <>
      {!online ? <p className="notice" role="status">{t("quiz_draft_pending")}</p> : null}
      {draftFailed ? <p role="status">{t("quiz_draft_failed")}</p> : null}
      <form
        id="quiz-form"
        data-quiz-id={quiz.quiz_id}
        data-quiz-version={quiz.version}
        onSubmit={submit}
      >
        {quiz.questions.map((question, index) => (
          <fieldset
            key={question.question_id}
            data-question-id={question.question_id}
            disabled={busy || !!result || !!submission.current}
          >
            <legend>
              {index + 1}. {question.prompt}
            </legend>
            {question.options.map((option) => (
              <label key={option.option_id} className="answer">
                <input
                  type="radio"
                  required
                  name={"question-" + question.question_id}
                  value={option.option_id}
                  checked={answers[question.question_id] === option.option_id}
                  onChange={() =>
                    setAnswers((old) => ({
                      ...old,
                      [question.question_id]: option.option_id,
                    }))
                  }
                />
                <span>{option.text}</span>
              </label>
            ))}
          </fieldset>
        ))}
        <button className="button" type="submit" disabled={busy || !!result || !online}>
          {t(busy ? "saving" : "submit_quiz")}
        </button>
      </form>
      <p className="notice" role="alert" hidden={!error}>
        {error}
      </p>
      {error ? <a className="text-link" href={location.pathname}>{t("reload_review")}</a> : null}
      <div id="quiz-result" ref={output} role="status" tabIndex={-1}>
        {result ? (
          <>
            <h3>{t("quiz_result")}</h3>
            <p>
              {t("score")}: {result.score}
            </p>
            {result.result.map((item) => (
              <p key={item.question_id}>
                {t(item.correct ? "correct" : "incorrect")} · {item.explanation}
              </p>
            ))}
            <LessonCompletion lessonId={quiz.lesson_id} />
          </>
        ) : null}
      </div>
    </>
  );
}

function LessonCompletion({lessonId, completed=false}:{lessonId:string;completed?:boolean}) {
 const [done,setDone]=useState(completed),[busy,setBusy]=useState(false),[message,setMessage]=useState("");
 const key=useRef(crypto.randomUUID());
 async function complete() {
  if(busy||done)return;
  if(!navigator.onLine){setMessage(t("quiz_online"));return;}
  setBusy(true);setMessage("");
  try {const value=await api<{completed:boolean}>(`/learning/lessons/${lessonId}/complete`,{method:"POST",key:key.current,body:{}});setDone(value.completed);}catch(e){setMessage(errorText(e));}finally{setBusy(false);}
 }
 if(document.body.dataset.member!=="true")return <a className="text-link" href={`/${locale}/sign-in/?return_to=${encodeURIComponent(location.pathname)}`}>{t("sign_in_save")}</a>;
 return <section className="lesson-completion"><button disabled={busy||done} onClick={()=>void complete()}>{t(done?"finished":busy?"saving":"complete_lesson")}</button><p role="status">{message}</p><a className="text-link" href={`/${locale}/learn/`}>{t("learn")}</a></section>;
}

export function mount() {
  const lesson=readBootstrap<{lesson_id?:string;completed?:boolean}>("lesson-bootstrap");
  if(lesson.lesson_id)mountIsland(document.getElementById("lesson-completion"),()=> <LessonCompletion lessonId={lesson.lesson_id!} completed={lesson.completed}/>);
  mountIsland(document.getElementById("quiz-island"), () => (
    <QuizIsland quiz={readBootstrap<Quiz>("quiz-bootstrap")} />
  ));
}
mount();
