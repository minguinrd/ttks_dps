// Forms carrying data-confirm="message" ask for confirmation before submitting.
document.addEventListener("submit", function (event) {
  var form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  var message = form.getAttribute("data-confirm");
  if (!message) return;
  event.preventDefault();
  // Modal chrome is translated via data-confirm-* attributes on <body>
  // (base.html); plain-English fallbacks keep the dialog usable without them.
  var chrome = document.body.dataset;
  Swal.fire({
    title: chrome.confirmTitle || "Are you sure?",
    text: message,
    icon: "warning",
    showCancelButton: true,
    confirmButtonText: chrome.confirmYes || "Yes",
    cancelButtonText: chrome.confirmCancel || "Cancel",
  }).then(function (result) {
    if (result.isConfirmed) {
      // form.submit() does not fire another submit event, so no re-prompt.
      form.submit();
    }
  });
});
