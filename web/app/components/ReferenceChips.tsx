export interface ReferenceChip {
  type: "skill" | "pkg" | "file";
  value: string;
  label: string;
  start: number;
  end: number;
}

export function parseReferences(text: string): ReferenceChip[] {
  const chips: ReferenceChip[] = [];
  const pattern = /@([a-z][a-z0-9_]*):([^\s@，。、；：！？""''（）《》【】…—～]+)/g;

  let match;
  while ((match = pattern.exec(text)) !== null) {
    let value = match[2];
    try {
      value = decodeURIComponent(value);
    } catch {
      // Keep a partially typed reference visible until it becomes valid.
    }
    chips.push({
      type: match[1] as ReferenceChip["type"],
      value,
      label: value,
      start: match.index,
      end: match.index + match[0].length,
    });
  }

  return chips;
}

export interface ReferenceChipDisplayProps {
  text: string;
  onRemoveChip?: (chip: ReferenceChip) => void;
}

export function ReferenceChipDisplay({ text, onRemoveChip }: ReferenceChipDisplayProps) {
  const chips = parseReferences(text);

  if (chips.length === 0) return null;

  return (
    <div className="reference-chips-display">
      {chips.map((chip, index) => (
        <div
          key={`${chip.type}-${chip.value}-${index}`}
          className={`reference-chip reference-chip-${chip.type}`}
          title={`${chip.type}: ${chip.value}`}
        >
          <span className="chip-icon">
            {chip.type === "skill" ? "⚡" : chip.type === "file" ? "📄" : "📦"}
          </span>
          <span className="chip-label">{chip.label}</span>
          {onRemoveChip && (
            <button
              type="button"
              className="chip-remove"
              onClick={() => onRemoveChip(chip)}
              aria-label="移除引用"
            >
              ×
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
