<script>
    let selectedDate = "";
    let currentMonth = new Date().getMonth();
    let currentYear = new Date().getFullYear();

    function updateCalendar() {
        const monthNames = [
            "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
            "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
        ];

        document.getElementById("currentMonthYear").textContent =
            `${monthNames[currentMonth]} ${currentYear}`;

        const calendarDays = document.getElementById("calendarDays");
        calendarDays.innerHTML = "";

        let firstDay = new Date(currentYear, currentMonth, 1).getDay();
        let daysInMonth = new Date(currentYear, currentMonth + 1, 0).getDate();

        for (let i = 0; i < firstDay; i++) {
            let emptyDiv = document.createElement("div");
            emptyDiv.classList.add("calendar-day");
            emptyDiv.style.visibility = "hidden";
            calendarDays.appendChild(emptyDiv);
        }

        for (let day = 1; day <= daysInMonth; day++) {
            let dayButton = document.createElement("div");
            dayButton.classList.add("calendar-day");
            dayButton.textContent = day;
            dayButton.onclick = () => selectDate(day);
            if (`${day}.${currentMonth + 1}.${currentYear}` === selectedDate) {
                dayButton.classList.add("selected");
            }
            calendarDays.appendChild(dayButton);
        }
    }

    function selectDate(day) {
        selectedDate = `${day}.${currentMonth + 1}.${currentYear}`;
        document.getElementById("selectedDate").value = selectedDate;
        updateCalendar();
    }

    function changeMonth(direction) {
        currentMonth += direction;
        if (currentMonth < 0) {
            currentMonth = 11;
            currentYear--;
        } else if (currentMonth > 11) {
            currentMonth = 0;
            currentYear++;
        }
        updateCalendar();
    }

    document.addEventListener("DOMContentLoaded", updateCalendar);
</script>
