// Header sign-in area and the sign-in message. User text is shown with textContent only.
export function renderAuth(state) {
  const { status, user } = state.auth;
  const signIn = document.getElementById("signin-button");
  const signOut = document.getElementById("signout-button");
  const who = document.getElementById("auth-user");
  const message = document.getElementById("auth-message");

  signIn.hidden = status !== "signed-out";
  signOut.hidden = status !== "signed-in";
  who.hidden = status !== "signed-in" && status !== "mock";
  if (status === "signed-in") who.textContent = `Signed in as ${user.display_name || user.email}`;
  else if (status === "mock") who.textContent = "Demo mode: no sign-in needed";

  message.hidden = !state.authMessage;
  message.textContent = state.authMessage || "";
}
