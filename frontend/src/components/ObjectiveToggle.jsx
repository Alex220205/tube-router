/**
 * What to optimise the journey for.
 *
 * WHY THIS EXISTS
 *     The engine's three objectives are the thing that makes this a planner
 *     rather than a shortest-path demo, and until this phase there was no way
 *     to ask for any of them but the default.
 *
 * WHAT THE 2021 VERSION DID
 *     Nothing. There was one search, optimising time, and no way to ask for
 *     anything else - the concept did not exist.
 *
 * WHAT'S NEW
 *     Radio buttons rather than a segmented control built from divs. They
 *     look the same once styled, and only one of them is reachable by
 *     keyboard, announced as a group, and understood by a screen reader - all
 *     of which matters more than usual on the control that offers step-free
 *     routing.
 */

// One list, so a fourth objective is a line here rather than a fourth branch
// somewhere. The values are the engine's own, not a translation: see
// backend/app/schemas/route.py.
export const OBJECTIVES = [
  { value: 'fastest', label: 'Fastest' },
  { value: 'fewest_changes', label: 'Fewest changes' },
  { value: 'step_free', label: 'Step-free' },
]

/**
 * @param {{value: string, onChange: (value: string) => void}} props
 */
export default function ObjectiveToggle({ value, onChange }) {
  return (
    <fieldset className="mt-4">
      <legend className="text-sm font-medium">Optimise for</legend>

      <div className="mt-1 flex gap-1 rounded-md bg-gray-100 p-1">
        {OBJECTIVES.map((objective) => (
          <label
            key={objective.value}
            className={`flex-1 cursor-pointer rounded px-2 py-1.5 text-center text-xs ${
              value === objective.value
                ? 'bg-white font-medium shadow-sm'
                : 'text-gray-600 hover:text-gray-900'
            }`}
          >
            {/* sr-only, not hidden. A hidden input cannot be focused, so the
                group would stop being reachable by keyboard - which is the
                whole reason these are radios and not buttons. */}
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
