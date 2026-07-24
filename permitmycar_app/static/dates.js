(() => {
  const form = document.getElementById("permit-form");
  const picker = document.getElementById("date-picker");
  const addButton = document.getElementById("add-date");
  const list = document.getElementById("selected-dates");
  if (!form || !picker || !addButton || !list) return;

  const selected = new Set();

  const render = () => {
    list.replaceChildren();
    [...selected].sort().forEach((value) => {
      const chip = document.createElement("span");
      chip.className = "date-chip";

      const label = document.createElement("span");
      const parsed = new Date(`${value}T12:00:00`);
      label.textContent = new Intl.DateTimeFormat(undefined, {
        weekday: "short",
        month: "short",
        day: "numeric",
      }).format(parsed);

      const remove = document.createElement("button");
      remove.type = "button";
      remove.setAttribute("aria-label", `Remove ${label.textContent}`);
      remove.textContent = "×";
      remove.addEventListener("click", () => {
        selected.delete(value);
        render();
      });

      const hidden = document.createElement("input");
      hidden.type = "hidden";
      hidden.name = "dates";
      hidden.value = value;

      chip.append(label, remove, hidden);
      list.append(chip);
    });
  };

  const addDate = () => {
    if (!picker.value) {
      picker.focus();
      return;
    }
    selected.add(picker.value);
    picker.value = "";
    render();
  };

  addButton.addEventListener("click", addDate);
  picker.addEventListener("change", addDate);
  form.addEventListener("submit", (event) => {
    if (selected.size === 0) {
      event.preventDefault();
      picker.setCustomValidity("Choose at least one permit date.");
      picker.reportValidity();
      picker.setCustomValidity("");
    }
  });
})();
