import type { SessionResource } from "@clerk/shared/types";

export async function verifySessionWithCurrentPassword(
  session: SessionResource,
  currentPassword: string
) {
  const verification = await session.startVerification({
    level: "first_factor"
  });

  if (verification.status !== "needs_first_factor") {
    return verification.status === "complete";
  }

  const supportsPassword = verification.supportedFirstFactors?.some(
    (factor) => factor.strategy === "password"
  );
  if (!supportsPassword) {
    return false;
  }

  const result = await session.attemptFirstFactorVerification({
    strategy: "password",
    password: currentPassword
  });
  return result.status === "complete";
}
