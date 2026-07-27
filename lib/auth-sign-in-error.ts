type ClerkSignInErrorLike = {
  code?: string;
  longMessage?: string;
};

export const INCORRECT_PASSWORD_MESSAGE =
  "That password is incorrect. Try again or reset your password.";

export const SIGN_IN_UNAVAILABLE_MESSAGE =
  "We could not sign you in. Check your details and try again.";

export function resolvePasswordSignInError(
  error: ClerkSignInErrorLike | null | undefined
) {
  if (error?.code === "form_password_incorrect") {
    return INCORRECT_PASSWORD_MESSAGE;
  }

  const longMessage = error?.longMessage?.trim();
  return longMessage || SIGN_IN_UNAVAILABLE_MESSAGE;
}
