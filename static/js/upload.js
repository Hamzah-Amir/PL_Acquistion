/* Drag-and-drop upload: accumulates a file list across drops and picks,
   because Amazon exports arrive as several separate archives. */
(function () {
  "use strict";

  var zone = document.getElementById("dropzone");
  var input = document.getElementById("sources");
  var list = document.getElementById("filelist");
  var submit = document.getElementById("upload-submit");
  var summary = document.getElementById("upload-summary");
  var limit = parseFloat(zone && zone.dataset.limitMb) || 500;
  if (!zone || !input) return;

  var files = [];

  function label(bytes) {
    if (bytes >= 1048576) return (bytes / 1048576).toFixed(1) + " MB";
    if (bytes >= 1024) return (bytes / 1024).toFixed(0) + " KB";
    return bytes + " B";
  }

  function kind(name) {
    var lower = name.toLowerCase();
    if (lower.endsWith(".zip")) return ["📦", "Archive"];
    if (lower.endsWith(".pdf")) return ["📄", "PDF"];
    if (lower.endsWith(".csv")) return ["📊", "CSV"];
    if (lower.endsWith(".xlsx") || lower.endsWith(".xlsm")) return ["📗", "Workbook"];
    return ["📎", "Other"];
  }

  function render() {
    list.innerHTML = "";
    var total = 0;
    files.forEach(function (file, index) {
      total += file.size;
      var meta = kind(file.name);
      var li = document.createElement("li");
      li.innerHTML =
        '<span aria-hidden="true">' + meta[0] + "</span>" +
        '<span class="fname" title="' + file.name.replace(/"/g, "&quot;") + '">' +
        file.name + "</span>" +
        '<span class="chip">' + meta[1] + "</span>" +
        '<span class="fsize">' + label(file.size) + "</span>";
      var remove = document.createElement("button");
      remove.type = "button";
      remove.className = "file-remove";
      remove.setAttribute("aria-label", "Remove " + file.name);
      remove.textContent = "×";
      remove.addEventListener("click", function () {
        files.splice(index, 1);
        sync();
      });
      li.appendChild(remove);
      list.appendChild(li);
    });

    var overLimit = total > limit * 1048576;
    submit.disabled = files.length === 0 || overLimit;
    if (!files.length) {
      summary.textContent = "";
    } else if (overLimit) {
      summary.innerHTML = '<span class="chip chip-bad">' + label(total) +
        " exceeds the " + limit + " MB limit</span>";
    } else {
      summary.innerHTML = '<span class="chip chip-brand">' + files.length +
        " file" + (files.length === 1 ? "" : "s") + "</span>" +
        '<span class="chip">' + label(total) + "</span>";
    }
  }

  // The file input is the thing actually posted, so keep it in step.
  function sync() {
    var transfer = new DataTransfer();
    files.forEach(function (file) { transfer.items.add(file); });
    input.files = transfer.files;
    render();
  }

  function add(incoming) {
    Array.prototype.forEach.call(incoming, function (file) {
      var duplicate = files.some(function (existing) {
        return existing.name === file.name && existing.size === file.size;
      });
      if (!duplicate) files.push(file);
    });
    sync();
  }

  zone.addEventListener("click", function () { input.click(); });
  zone.addEventListener("keydown", function (event) {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); input.click(); }
  });
  input.addEventListener("change", function () { add(input.files); });

  ["dragenter", "dragover"].forEach(function (name) {
    zone.addEventListener(name, function (event) {
      event.preventDefault();
      zone.classList.add("is-over");
    });
  });
  ["dragleave", "drop"].forEach(function (name) {
    zone.addEventListener(name, function (event) {
      event.preventDefault();
      if (name === "dragleave" && zone.contains(event.relatedTarget)) return;
      zone.classList.remove("is-over");
    });
  });
  zone.addEventListener("drop", function (event) {
    if (event.dataTransfer && event.dataTransfer.files) add(event.dataTransfer.files);
  });

  var form = document.getElementById("upload-form");
  form.addEventListener("submit", function () {
    submit.disabled = true;
    submit.textContent = "Uploading…";
  });

  render();
})();
