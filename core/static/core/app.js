// Veggohandla – a little vanilla JS on top of htmx.
(function () {
  "use strict";

  const csrf = () => document.querySelector("meta[name=csrf-token]").content;

  // --- dialog (recipe picker etc.) ------------------------------------
  const dialog = () => document.getElementById("dialog");
  document.addEventListener("htmx:afterSwap", (e) => {
    if (e.detail.target.id === "dialog-content") {
      const d = dialog();
      if (!d.open) d.showModal();
      const input = d.querySelector("input[type=search]");
      if (input) input.focus();
    }
  });
  document.addEventListener("click", (e) => {
    const d = dialog();
    if (d && e.target === d) d.close(); // click on the backdrop
    if (e.target.closest("[data-close-dialog]")) d.close();
  });

  // --- drag and drop in the week planner --------------------------------
  function initSortable(root) {
    if (!window.Sortable) return;
    root.querySelectorAll(".meals").forEach((list) => {
      if (list._sortable) return;
      list._sortable = Sortable.create(list, {
        group: "meals",
        filter: "button",
        preventOnFilter: false,
        animation: 150,
        ghostClass: "sortable-ghost",
        dragClass: "sortable-drag",
        onEnd(evt) {
          const to = evt.to;
          const order = [...to.querySelectorAll(".meal")].map((li) => li.dataset.id).join(",");
          const body = new URLSearchParams({ id: evt.item.dataset.id, date: to.dataset.date, order });
          fetch(to.dataset.moveUrl, {
            method: "POST",
            headers: { "X-CSRFToken": csrf(), "Content-Type": "application/x-www-form-urlencoded" },
            body,
          }).then((r) => {
            if (!r.ok) location.reload();
            document.body.dispatchEvent(new Event("plan-changed"));
            // Refresh the dates on the remove/servings buttons: reload both days.
            [evt.from, evt.to].forEach((l) => {
              const day = l.closest(".day");
              if (day) htmx.ajax("GET", day.dataset.refresh, { target: day, swap: "outerHTML" });
            });
          });
        },
      });
    });
  }
  htmx.onLoad(initSortable);

  // --- copy the list as text --------------------------------------
  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-share-list]");
    if (!b) return;
    const ta = document.getElementById("list-text");
    try {
      await navigator.clipboard.writeText(ta.value);
      b.querySelector("span").textContent = b.dataset.copied;
    } catch (_) {
      ta.hidden = false;
      ta.select();
    }
  });

  // --- confirm dangerous actions ---------------------------------------
  document.addEventListener("submit", (e) => {
    const msg = e.target.dataset.confirm;
    if (msg && !confirm(msg)) e.preventDefault();
  });
})();
