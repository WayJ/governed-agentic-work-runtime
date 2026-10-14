/* Governed Work Runtime — website enhancement script (progressive only).
 * Apache-2.0 (project asset). No external requests; no content is hidden
 * without this script: it only ADDS copy buttons, an aria-live region and
 * the recovery Prev/Next stepping. Pages remain fully readable without JS. */
(function () {
  "use strict";

  var zh = document.documentElement.lang.indexOf("zh") === 0;
  var MSG = zh ? {
    copy: "复制",
    copied: "已复制：",
    copyFailed: "复制失败——请手动选中命令文本并复制。",
    prev: "上一阶段",
    next: "下一阶段",
    stages: "恢复阶段，可用左右方向键切换",
    stageOf: function (n, total) { return "第 " + n + " / " + total + " 步"; },
    movedTo: function (n, total) { return "已到第 " + n + " / " + total + " 步"; }
  } : {
    copy: "Copy",
    copied: "Copied: ",
    copyFailed: "Copy failed — select the command text and copy manually.",
    prev: "Previous stage",
    next: "Next stage",
    stages: "Recovery stages; use the arrow keys to move",
    stageOf: function (n, total) { return "Stage " + n + " of " + total; },
    movedTo: function (n, total) { return "Moved to stage " + n + " of " + total; }
  };

  var live = document.createElement("div");
  live.className = "live-region";
  live.setAttribute("aria-live", "polite");
  document.body.appendChild(live);

  function announce(text) {
    live.textContent = "";
    window.setTimeout(function () { live.textContent = text; }, 50);
  }

  /* Copy buttons — copy the exact visible text of the code block. */
  Array.prototype.forEach.call(
    document.querySelectorAll("pre[data-copyable]"),
    function (pre) {
      var block = pre.closest(".code-block") || pre.parentElement;
      if (!block) { return; }
      var label = pre.getAttribute("data-label") || "";
      var button = document.createElement("button");
      button.type = "button";
      button.className = "copy-btn";
      button.textContent = MSG.copy;
      button.setAttribute("aria-label", MSG.copy + " " + label);
      button.addEventListener("click", function () {
        function fail() { announce(MSG.copyFailed); }
        if (!(navigator.clipboard && window.isSecureContext)) {
          fail();
          return;
        }
        navigator.clipboard.writeText(pre.textContent).then(
          function () { announce(MSG.copied + label + "."); },
          fail);
      });
      block.appendChild(button);
    });

  /* Recovery stepping — all six stages stay visible; JS only marks the
   * current stage and adds Prev/Next + arrow-key controls. */
  var stages = Array.prototype.slice.call(
    document.querySelectorAll("#recovery-stages .stage"));
  if (stages.length) {
    var total = stages.length;
    var index = 0;
    stages.forEach(function (stage, i) { stage.dataset.stage = String(i + 1); });

    var controls = document.createElement("div");
    controls.className = "recovery-controls";
    var prev = document.createElement("button");
    prev.type = "button";
    prev.textContent = MSG.prev;
    prev.disabled = true;
    var status = document.createElement("span");
    status.className = "recovery-status";
    var next = document.createElement("button");
    next.type = "button";
    next.textContent = MSG.next;
    controls.appendChild(prev);
    controls.appendChild(status);
    controls.appendChild(next);
    stages[0].parentElement.insertBefore(controls, stages[0]);

    var list = stages[0].parentElement;
    list.tabIndex = 0;
    list.setAttribute("aria-label", MSG.stages);

    function render() {
      stages.forEach(function (stage, i) {
        if (i === index) {
          stage.setAttribute("aria-current", "step");
        } else {
          stage.removeAttribute("aria-current");
        }
      });
      status.textContent = MSG.stageOf(index + 1, total);
      prev.disabled = index === 0;
      next.disabled = index === total - 1;
    }

    function goTo(i) {
      var target = Math.max(0, Math.min(total - 1, i));
      if (target === index) { return; }
      index = target;
      render();
      announce(MSG.movedTo(index + 1, total));
      stages[index].scrollIntoView({ block: "nearest" });
    }

    prev.addEventListener("click", function () { goTo(index - 1); });
    next.addEventListener("click", function () { goTo(index + 1); });
    list.addEventListener("keydown", function (event) {
      if (event.key === "ArrowRight") { goTo(index + 1); event.preventDefault(); }
      if (event.key === "ArrowLeft") { goTo(index - 1); event.preventDefault(); }
    });
    render();
  }
}());
