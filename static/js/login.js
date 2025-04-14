document.addEventListener("DOMContentLoaded", function() {
    const toggleThemeButton = document.createElement("button");
    toggleThemeButton.textContent = "🌙";
    toggleThemeButton.classList.add("btn", "btn-dark", "position-fixed", "top-0", "end-0", "m-3");

    document.body.appendChild(toggleThemeButton);

    toggleThemeButton.addEventListener("click", function() {
        document.body.classList.toggle("dark-mode");
        localStorage.setItem("darkMode", document.body.classList.contains("dark-mode"));
    });

    if (localStorage.getItem("darkMode") === "true") {
        document.body.classList.add("dark-mode");
    }
});
