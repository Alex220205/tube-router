/** What to optimise the journey for. */

// One list, so a fourth objective is a line here rather than a fourth branch somewhere.
// The values are the engine's own, not a translation: see backend/app/schemas/route.py.
export const OBJECTIVES = [
  { value: 'fastest', label: 'Fastest' },
  { value: 'fewest_changes', label: 'Fewest changes' },
  { value: 'step_free', label: 'Step-free' },
]

/** @param {{value: string, onChange: (value: string) => void}} props */
export default function ObjectiveToggle({ value, onChange }) {
  return (
    <fieldset className="mt-5">
      <legend className="text-tfl-grey text-xs font-bold tracking-wider uppercase">
        Optimise for
      </legend>

      <div className="border-tfl-line mt-1.5 flex border-2">
        {OBJECTIVES.map((objective, index) => (
          <label
            key={objective.value}
            className={`flex-1 cursor-pointer px-2 py-2 text-center text-xs font-medium transition-colors ${
              index > 0 ? 'border-tfl-line border-l-2' : ''
            } ${
              value === objective.value
                ? 'bg-tfl-blue text-white'
                : 'text-tfl-grey hover:bg-tfl-paper hover:text-tfl-ink bg-white'
            }`}
          >
            {/* sr-only, not hidden. A hidden input cannot be focused, so the group
                would stop being reachable by keyboard - which is the whole reason
                these are radios and not buttons. */}
            <input
              type="radio"
              name="objective"
              value={objective.value}
              checked={value === objective.value}
              onChange={() => onChange(objective.value)}
              className="sr-only"
            />
            {objective.label}
          </label>
        ))}
      </div>
    </fieldset>
  )
}
