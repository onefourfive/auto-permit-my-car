(() => {
  const form = document.getElementById("permit-form");
  const calendar = document.getElementById("date-calendar");
  const grid = document.getElementById("calendar-grid");
  const heading = document.getElementById("calendar-heading");
  const previousButton = document.getElementById("previous-month");
  const nextButton = document.getElementById("next-month");
  const clearButton = document.getElementById("clear-dates");
  const summary = document.getElementById("selection-summary");
  const error = document.getElementById("calendar-error");
  const inputs = document.getElementById("selected-dates");
  if (
    !form || !calendar || !grid || !heading || !previousButton ||
    !nextButton || !clearButton || !summary || !error || !inputs
  ) return;

  const selected = new Set();
  const monthFormatter = new Intl.DateTimeFormat(undefined, {
    month: "long",
    year: "numeric",
  });
  const fullDateFormatter = new Intl.DateTimeFormat(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });

  const parseISODate = (value) => {
    const [year, month, day] = value.split("-").map(Number);
    return new Date(year, month - 1, day, 12);
  };

  const toISODate = (value) => {
    const year = value.getFullYear();
    const month = String(value.getMonth() + 1).padStart(2, "0");
    const day = String(value.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  };

  const atNoon = (value) =>
    new Date(value.getFullYear(), value.getMonth(), value.getDate(), 12);

  const addDays = (value, amount) => {
    const result = atNoon(value);
    result.setDate(result.getDate() + amount);
    return result;
  };

  const daysInMonth = (year, month) =>
    new Date(year, month + 1, 0).getDate();

  const addMonths = (value, amount) => {
    const target = new Date(
      value.getFullYear(),
      value.getMonth() + amount,
      1,
      12,
    );
    target.setDate(
      Math.min(value.getDate(), daysInMonth(target.getFullYear(), target.getMonth())),
    );
    return target;
  };

  const sameMonth = (first, second) =>
    first.getFullYear() === second.getFullYear() &&
    first.getMonth() === second.getMonth();

  const minimumDate = parseISODate(calendar.dataset.minDate);
  const minimumISO = toISODate(minimumDate);
  const today = atNoon(new Date());
  const todayISO = toISODate(today);
  let visibleMonth = new Date(today.getFullYear(), today.getMonth(), 1, 12);
  if (visibleMonth < new Date(minimumDate.getFullYear(), minimumDate.getMonth(), 1, 12)) {
    visibleMonth = new Date(
      minimumDate.getFullYear(),
      minimumDate.getMonth(),
      1,
      12,
    );
  }
  let activeDate = today < minimumDate ? minimumDate : today;

  const renderSelection = () => {
    const sorted = [...selected].sort();
    inputs.replaceChildren();
    sorted.forEach((value) => {
      const hidden = document.createElement("input");
      hidden.type = "hidden";
      hidden.name = "dates";
      hidden.value = value;
      inputs.append(hidden);
    });

    const count = sorted.length;
    summary.textContent =
      count === 0 ? "No dates selected" :
      count === 1 ? "1 date selected" :
      `${count} dates selected`;
    clearButton.hidden = count === 0;
    if (count > 0) error.hidden = true;
  };

  const focusDate = (value) => {
    const button = grid.querySelector(`[data-date="${toISODate(value)}"]`);
    if (button) button.focus();
  };

  const toggleDate = (value, button) => {
    const isoDate = toISODate(value);
    if (selected.has(isoDate)) {
      selected.delete(isoDate);
    } else {
      selected.add(isoDate);
    }
    activeDate = value;
    const isSelected = selected.has(isoDate);
    button.classList.toggle("is-selected", isSelected);
    button.setAttribute("aria-selected", String(isSelected));
    renderSelection();
  };

  const moveFocus = (value) => {
    const target = value < minimumDate ? minimumDate : value;
    activeDate = target;
    if (!sameMonth(target, visibleMonth)) {
      visibleMonth = new Date(
        target.getFullYear(),
        target.getMonth(),
        1,
        12,
      );
      renderCalendar(true);
    } else {
      grid.querySelectorAll(".calendar-day").forEach((button) => {
        button.tabIndex = button.dataset.date === toISODate(target) ? 0 : -1;
      });
      focusDate(target);
    }
  };

  const handleDayKeydown = (event, value) => {
    let target;
    switch (event.key) {
      case "ArrowLeft":
        target = addDays(value, -1);
        break;
      case "ArrowRight":
        target = addDays(value, 1);
        break;
      case "ArrowUp":
        target = addDays(value, -7);
        break;
      case "ArrowDown":
        target = addDays(value, 7);
        break;
      case "Home":
        target = addDays(value, -value.getDay());
        break;
      case "End":
        target = addDays(value, 6 - value.getDay());
        break;
      case "PageUp":
        target = addMonths(value, -1);
        break;
      case "PageDown":
        target = addMonths(value, 1);
        break;
      default:
        return;
    }
    event.preventDefault();
    moveFocus(target);
  };

  function renderCalendar(shouldFocus = false) {
    heading.textContent = monthFormatter.format(visibleMonth);
    grid.replaceChildren();

    const firstDay = new Date(
      visibleMonth.getFullYear(),
      visibleMonth.getMonth(),
      1,
      12,
    );
    const count = daysInMonth(
      visibleMonth.getFullYear(),
      visibleMonth.getMonth(),
    );

    for (let index = 0; index < firstDay.getDay(); index += 1) {
      const empty = document.createElement("span");
      empty.className = "calendar-empty";
      empty.setAttribute("role", "gridcell");
      grid.append(empty);
    }

    for (let day = 1; day <= count; day += 1) {
      const value = new Date(
        visibleMonth.getFullYear(),
        visibleMonth.getMonth(),
        day,
        12,
      );
      const isoDate = toISODate(value);
      const isDisabled = isoDate < minimumISO;
      const isSelected = selected.has(isoDate);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "calendar-day";
      button.textContent = String(day);
      button.dataset.date = isoDate;
      button.setAttribute("role", "gridcell");
      button.setAttribute("aria-label", fullDateFormatter.format(value));
      button.setAttribute("aria-selected", String(isSelected));
      button.disabled = isDisabled;
      button.tabIndex = isoDate === toISODate(activeDate) ? 0 : -1;
      button.classList.toggle("is-selected", isSelected);
      button.classList.toggle("is-today", isoDate === todayISO);

      if (!isDisabled) {
        button.addEventListener("click", () => toggleDate(value, button));
        button.addEventListener("keydown", (event) =>
          handleDayKeydown(event, value),
        );
      }
      grid.append(button);
    }

    const minimumMonth = new Date(
      minimumDate.getFullYear(),
      minimumDate.getMonth(),
      1,
      12,
    );
    previousButton.disabled = visibleMonth <= minimumMonth;
    if (shouldFocus) focusDate(activeDate);
  }

  const changeVisibleMonth = (amount) => {
    visibleMonth = addMonths(visibleMonth, amount);
    const firstAvailable = new Date(
      visibleMonth.getFullYear(),
      visibleMonth.getMonth(),
      1,
      12,
    );
    activeDate = firstAvailable < minimumDate ? minimumDate : firstAvailable;
    renderCalendar(true);
  };

  previousButton.addEventListener("click", () => changeVisibleMonth(-1));
  nextButton.addEventListener("click", () => changeVisibleMonth(1));
  clearButton.addEventListener("click", () => {
    selected.clear();
    renderSelection();
    renderCalendar();
    focusDate(activeDate);
  });

  form.addEventListener("submit", (event) => {
    if (selected.size === 0) {
      event.preventDefault();
      error.hidden = false;
      focusDate(activeDate);
    }
  });

  renderSelection();
  renderCalendar();
})();
