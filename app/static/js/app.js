// Progressive enhancements: every page works without this file.

// Forms carrying data-confirm="message" ask for confirmation before submitting.
document.addEventListener("submit", function (event) {
  var form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  var message = form.getAttribute("data-confirm");
  if (message && typeof Swal !== "undefined") {
    event.preventDefault();
    // Modal chrome is translated via data-confirm-* attributes on <body>
    // (base.html); plain-English fallbacks keep the dialog usable without them.
    var chrome = document.body.dataset;
    var dark = document.documentElement.getAttribute("data-bs-theme") === "dark";
    Swal.fire({
      title: chrome.confirmTitle || "Are you sure?",
      text: message,
      icon: "warning",
      theme: dark ? "dark" : "light",
      showCancelButton: true,
      reverseButtons: true,
      focusCancel: true,
      confirmButtonText: chrome.confirmYes || "Yes",
      cancelButtonText: chrome.confirmCancel || "Cancel",
      confirmButtonColor: getComputedStyle(document.documentElement)
        .getPropertyValue("--brand-accent")
        .trim(),
    }).then(function (result) {
      if (result.isConfirmed) {
        markBusy(form, event.submitter);
        // form.submit() does not fire another submit event, so no re-prompt.
        form.submit();
      }
    });
    return;
  }
  markBusy(form, event.submitter);
});

// Block double submits: the clicked button shows a busy state until the
// next page loads. GET forms (filters) are left alone.
function markBusy(form, submitter) {
  if ((form.method || "get").toLowerCase() !== "post") return;
  var button = submitter || form.querySelector("[type=submit]");
  if (!button) return;
  // Defer so the button's own name/value is still submitted.
  setTimeout(function () {
    button.setAttribute("aria-busy", "true");
    button.disabled = true;
    var icon = button.querySelector(".ph");
    if (icon) icon.className = "ph ph-circle-notch";
  }, 0);
}

// Pages restored from the back/forward cache must not keep busy buttons.
window.addEventListener("pageshow", function (event) {
  if (!event.persisted) return;
  document.querySelectorAll("[aria-busy=true]").forEach(function (button) {
    button.removeAttribute("aria-busy");
    button.disabled = false;
  });
});

// Filter forms (data-autosubmit) apply on change; their Apply button hides.
document.addEventListener("change", function (event) {
  var field = event.target;
  if (!(field instanceof HTMLSelectElement || field instanceof HTMLInputElement)) return;
  var form = field.form;
  if (form && form.hasAttribute("data-autosubmit")) form.requestSubmit();
});

// Theme toggle (navbar): flips light/dark and remembers the choice in this
// browser; until it is used the page follows the system setting (see the
// inline script in base.html).
document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
  var root = document.documentElement;
  function sync() {
    button.setAttribute("aria-pressed", String(root.getAttribute("data-bs-theme") === "dark"));
  }
  button.hidden = false;
  sync();
  new MutationObserver(sync).observe(root, { attributes: true, attributeFilter: ["data-bs-theme"] });
  button.addEventListener("click", function () {
    var next = root.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-bs-theme", next);
    try {
      localStorage.setItem("theme", next);
    } catch (e) {
      /* private mode: the switch still applies to this page */
    }
  });
});

// Forms with data-draft keep unsent text in this tab (sessionStorage, so it
// dies with the tab) and ask before the page is left with unsaved changes.
// Submitting or following a [data-draft-discard] link drops the draft.
document.querySelectorAll("form[data-draft]").forEach(function (form) {
  var key = "draft:" + form.getAttribute("data-draft");
  var fields = Array.from(form.elements).filter(function (el) {
    return el.name && el.name !== "csrf_token" && el.type !== "hidden" && el.type !== "submit";
  });
  var dirty = false;
  var serverFilled = fields.some(function (el) {
    return (el.type === "text" || el.tagName === "TEXTAREA") && el.value.trim();
  });

  function store() {
    var data = {};
    fields.forEach(function (el) {
      if (el.type === "radio") {
        if (el.checked) data[el.name] = el.value;
      } else {
        data[el.name] = el.value;
      }
    });
    try {
      sessionStorage.setItem(key, JSON.stringify(data));
    } catch (e) {
      /* storage full or disabled: the warning below still protects the text */
    }
  }

  function drop() {
    dirty = false;
    try {
      sessionStorage.removeItem(key);
    } catch (e) {}
  }

  // Restore only into an untouched form: a re-rendered form (validation
  // errors) already carries what was posted.
  if (!serverFilled) {
    try {
      var saved = JSON.parse(sessionStorage.getItem(key) || "null");
      if (saved) {
        fields.forEach(function (el) {
          if (!(el.name in saved)) return;
          if (el.type === "radio") el.checked = el.value === saved[el.name];
          else el.value = saved[el.name];
        });
        dirty = true;
      }
    } catch (e) {}
  }

  // Re-rendered after a failed submit: what is on screen is still unsent.
  if (form.querySelector("[aria-invalid=true]")) {
    dirty = true;
    store();
  }

  form.addEventListener("input", function () {
    dirty = true;
    store();
  });
  form.addEventListener("change", store);
  form.addEventListener("submit", drop);
  form.querySelectorAll("[data-draft-discard]").forEach(function (link) {
    link.addEventListener("click", drop);
  });
  window.addEventListener("beforeunload", function (event) {
    if (!dirty) return;
    event.preventDefault();
    event.returnValue = "";
  });
});

// After a failed submit, put the cursor on the first field with an error.
var firstInvalid = document.querySelector("main [aria-invalid=true]");
if (firstInvalid) firstInvalid.focus();

// Ctrl/Cmd + Enter sends a textarea's form (the comment composer).
document.addEventListener("keydown", function (event) {
  var field = event.target;
  if (event.key !== "Enter" || !(event.ctrlKey || event.metaKey)) return;
  if (!(field instanceof HTMLTextAreaElement) || !field.hasAttribute("data-submit-shortcut")) return;
  if (!field.value.trim() || !field.form) return;
  event.preventDefault();
  field.form.requestSubmit();
});

// GET filter forms leave empty and default-valued fields out of the URL, so
// links stay short and "no filter" reads as no parameter at all. Listening
// in the capture phase catches the formdata event of every form.
document.addEventListener(
  "formdata",
  function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement) || form.method.toLowerCase() !== "get") return;
    Array.from(event.formData.keys()).forEach(function (name) {
      var field = form.elements.namedItem(name);
      var fallback = field && field.dataset ? field.dataset.default : undefined;
      var value = event.formData.get(name);
      if (value === "" || (fallback !== undefined && value === fallback)) {
        event.formData.delete(name);
      }
    });
  },
  true,
);

// <time data-relative> → "hace 3 horas" in the page language; the absolute
// timestamp moves to the tooltip.
function relativeTimes() {
  if (!("RelativeTimeFormat" in Intl)) return;
  var lang = document.documentElement.lang || "es";
  var rtf = new Intl.RelativeTimeFormat(lang, { numeric: "auto" });
  var units = [
    ["year", 31536000],
    ["month", 2592000],
    ["week", 604800],
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];
  document.querySelectorAll("time[data-relative]").forEach(function (el) {
    var then = new Date(el.getAttribute("datetime"));
    if (isNaN(then)) return;
    var seconds = (then.getTime() - Date.now()) / 1000;
    var text = rtf.format(0, "minute");
    for (var i = 0; i < units.length; i++) {
      if (Math.abs(seconds) >= units[i][1]) {
        text = rtf.format(Math.round(seconds / units[i][1]), units[i][0]);
        break;
      }
    }
    if (!el.title) el.title = then.toLocaleString(lang);
    el.textContent = text;
  });
}

document.addEventListener("DOMContentLoaded", function () {
  relativeTimes();
  // Flash messages render as Bootstrap toasts (base.html); show them on load.
  var container = document.getElementById("flash-toasts");
  if (!container || typeof bootstrap === "undefined") return;
  container.querySelectorAll(".toast").forEach(function (el) {
    new bootstrap.Toast(el).show();
  });
});
