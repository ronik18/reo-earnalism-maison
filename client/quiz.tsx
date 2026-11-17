import { useRef, useState, type FormEvent } from "react";
import { createRoot } from "react-dom/client";
import { api, errorText, readBootstrap, t } from "./api";
interface Quiz {
  quiz_id: string;
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
  const [answers, setAnswers] = useState<Record<string, string>>({});
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
        <button className="button" type="submit" disabled={busy || !!result}>
          {t(busy ? "saving" : "submit_quiz")}
        </button>
      </form>
      <p className="notice" role="alert" hidden={!error}>
        {error}
      </p>
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
          </>
        ) : null}
      </div>
    </>
  );
}
const host = document.getElementById("quiz-island");
if (host)
  createRoot(host).render(
    <QuizIsland quiz={readBootstrap<Quiz>("quiz-bootstrap")} />,
  );
