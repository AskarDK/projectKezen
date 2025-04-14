document.addEventListener("DOMContentLoaded", function () {
    console.log("✅ JS загружен");

    let registerForm = document.getElementById("registerForm");
    let loginForm = document.getElementById("loginForm");

    async function handleSubmit(event, form, url, successRedirect) {
        event.preventDefault();
        console.log(`📨 Отправка данных на: ${url}`);

        let formData = new FormData(form);

        try {
            let response = await fetch(url, {
                method: "POST",
                body: formData
            });

            console.log("📥 Ответ получен:", response);

            // Если сервер отправил JSON-ошибку
            if (response.headers.get("content-type")?.includes("application/json")) {
                let jsonResponse = await response.json();
                if (jsonResponse.error) {
                    console.log("⚠️ Ошибка от сервера:", jsonResponse.error);
                    showAlert(jsonResponse.error, "danger");
                    return;
                }
            }

            if (response.redirected) {
                console.log(`🔀 Перенаправление на ${response.url}`);
                window.location.href = response.url;
                return;
            }

            let text = await response.text();
            console.log("📄 Текст ответа сервера:", text);

            let parser = new DOMParser();
            let doc = parser.parseFromString(text, "text/html");
            let alertBox = doc.querySelector(".alert");

            if (alertBox) {
                console.log("⚠️ Сообщение от сервера:", alertBox.innerText);
                showAlert(alertBox.innerText, "danger");
            } else {
                console.log(`✅ Успешный вход, переход на ${successRedirect}`);
                window.location.href = successRedirect;
            }
        } catch (error) {
            console.error("❌ Ошибка при отправке запроса:", error);
            showAlert("Произошла ошибка при отправке запроса!", "danger");
        }
    }

    function showAlert(message, type) {
        let alertDiv = document.createElement("div");
        alertDiv.className = `alert alert-${type}`;
        alertDiv.innerText = message;
        document.body.prepend(alertDiv);

        setTimeout(() => {
            alertDiv.remove();
        }, 3000);
    }

    if (registerForm) {
        console.log("📌 Форма регистрации найдена");
        registerForm.addEventListener("submit", function (event) {
            handleSubmit(event, registerForm, "/register", "/login");
        });
    } else {
        console.warn("⚠️ Форма регистрации не найдена!");
    }

    if (loginForm) {
        console.log("📌 Форма входа найдена");
        loginForm.addEventListener("submit", function (event) {
            handleSubmit(event, loginForm, "/login", "/");
        });
    } else {
        console.warn("⚠️ Форма входа не найдена!");
    }
});
