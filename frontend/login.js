const form = document.getElementById("auth-form");
const submitBtn = document.getElementById("submit-btn");
const errorEl = document.getElementById("auth-error");
const subtitle = document.getElementById("auth-subtitle");
const switchPrompt = document.getElementById("switch-prompt");
const switchLink = document.getElementById("switch-link");

let mode = "login"; // or "signup"

function setMode(next) {
  mode = next;
  errorEl.textContent = "";
  if (mode === "login") {
    subtitle.textContent = "Sign in to your account";
    submitBtn.textContent = "Sign in";
    switchPrompt.textContent = "No account yet?";
    switchLink.textContent = "Create one";
  } else {
    subtitle.textContent = "Create an account";
    submitBtn.textContent = "Sign up";
    switchPrompt.textContent = "Already have an account?";
    switchLink.textContent = "Sign in";
  }
}

switchLink.addEventListener("click", (e) => {
  e.preventDefault();
  setMode(mode === "login" ? "signup" : "login");
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  errorEl.textContent = "";
  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;

  const endpoint = mode === "login" ? "/api/auth/login" : "/api/auth/signup";
  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();
    if (!res.ok) {
      errorEl.textContent = data.detail || "Something went wrong";
      return;
    }
    window.location.href = "/index.html";
  } catch (err) {
    errorEl.textContent = "Could not reach the server";
  }
});
