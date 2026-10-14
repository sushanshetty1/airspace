export type TaskLook = { color: string; letter: string }

const COLORS = ['var(--agent-a)', 'var(--agent-b)', 'var(--agent-c)', 'var(--agent-d)']

/** Task n's colour and letter: the four agent colours, with the letter telling five and six apart. */
export const taskLook = (i: number): TaskLook => ({ color: COLORS[i % COLORS.length], letter: String.fromCharCode(65 + i) })
