export const SYSTEM_PROMPT_MAX_CHARS = 12000;

export function systemPromptLengthError(value: string): string {
  const overflow = value.length - SYSTEM_PROMPT_MAX_CHARS;
  if (overflow <= 0) {
    return "";
  }
  return `System prompt must be ${SYSTEM_PROMPT_MAX_CHARS} characters or fewer. Remove ${overflow} ${overflow === 1 ? "character" : "characters"} before saving.`;
}