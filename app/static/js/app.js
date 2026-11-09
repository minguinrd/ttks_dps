// Forms carrying data-confirm="message" ask for confirmation before submitting.
document.addEventListener("submit", function (event) {
  var form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  var message = form.getAttribute("data-confirm");
  if (!message) return;
  event.preventDefault();
  Swal.fire({
    title: "Are you sure?",
    text: message,
    icon: "warning",
    showCancelButton: true,
    confirmButtonText: "Yes",
    cancelButtonText: "Cancel",
  }).then(function (result) {
    if (result.isConfirmed) {
      // form.submit() does not fire another submit event, so no re-prompt.
      form.submit();
    }
  });
});
