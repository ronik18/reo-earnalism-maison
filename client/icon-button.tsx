/** Icon-only button: 44 px square, the accessible name is required. Glyphs come from the sprite in base.html. */
export function IconButton({ label, icon, onClick, disabled }: { label: string; icon: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button type="button" className="icon-button" aria-label={label} disabled={disabled} onClick={onClick}>
      <svg aria-hidden="true" focusable="false"><use href={`#${icon}`} /></svg>
    </button>
  );
}
