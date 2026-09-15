$(".save-button").on("click", save);
$("#signup").submit(handleSubmit);
$(document).ready(init);
$.ajax({ url: "https://example.invalid/api?token=fake-js5-jquery-token", method: "POST" });
$.get("/local/data.json");
$.fn.flashMessage = function () { return this; };
