/* Governed Work Runtime — website enhancement script (progressive only).
 * Apache-2.0 (project asset). No external requests; no content is hidden
 * without this script: it only ADDS copy buttons, an aria-live region and
 * the recovery Prev/Next stepping + live stage inspector. Pages remain fully
 * readable without JS. */
(function () {
  "use strict";

  var zh = document.documentElement.lang.indexOf("zh") === 0;
  var MSG = zh ? {
    copy: "复制",
    copied: "已复制：",
    copyFailed: "复制失败——请手动选中命令文本并复制。",
    prev: "上一阶段",
    next: "下一阶段",
    stages: "恢复阶段，可用左右方向键或点击卡片切换",
    stageOf: function (n, total) { return "第 " + n + " / " + total + " 步"; },
    movedTo: function (n, total) { return "已到第 " + n + " / " + total + " 步"; },
    lblCommand: "触发命令 / 动作",
    lblRuntime: "Runtime 持久状态",
    lblExternal: "外部 OA 存储状态",
    snapshots: [
      {
        cmd: "propose_action(expense.submit)",
        rt: "status: active · decision: rejected (E05 missing)",
        ext: "applications: 0 (未放行外部调用)"
      },
      {
        cmd: "register_wait(requirement=E05, owner=finance)",
        rt: "status: waiting · waits[0]: waiting (持久落盘)",
        ext: "applications: 0 (Agent 会话可安全退出)"
      },
      {
        cmd: "record_evidence(approval) + verify_pending",
        rt: "status: active · E05: satisfied · operation: admitted",
        ext: "applications: 0 (准备派发唯一 operation_id)"
      },
      {
        cmd: "dispatch(operation_id) → 外部提交后进程崩溃",
        rt: "status: active · op: outcome_unknown",
        ext: "applications: 1 (OA 已落盘，但响应丢失)"
      },
      {
        cmd: "reconcile(operation_id) → 按原 business_key 查询",
        rt: "status: active · op: confirmed_succeeded (找回原回执)",
        ext: "applications: 1 (零重复提交)"
      },
      {
        cmd: "request_completion() → 核对回执与已验证证据",
        rt: "status: closed · outcome: succeeded",
        ext: "applications: 1 (端到端可证明闭环)"
      }
    ]
  } : {
    copy: "Copy",
    copied: "Copied: ",
    copyFailed: "Copy failed — select the command text and copy manually.",
    prev: "Previous stage",
    next: "Next stage",
    stages: "Recovery stages; use the arrow keys or click a stage card to move",
    stageOf: function (n, total) { return "Stage " + n + " of " + total; },
    movedTo: function (n, total) { return "Moved to stage " + n + " of " + total; },
    lblCommand: "Runtime command / action",
    lblRuntime: "Durable runtime state",
    lblExternal: "External OA store",
    snapshots: [
      {
        cmd: "propose_action(expense.submit)",
        rt: "status: active · decision: rejected (E05 missing)",
        ext: "applications: 0 (gated before external call)"
      },
      {
        cmd: "register_wait(requirement=E05, owner=finance)",
        rt: "status: waiting · waits[0]: waiting (durable)",
        ext: "applications: 0 (no live session needed)"
      },
      {
        cmd: "record_evidence(approval) + verify_pending",
        rt: "status: active · E05: satisfied · operation: admitted",
        ext: "applications: 0 (logical operation prepared)"
      },
      {
        cmd: "dispatch(operation_id) → worker exits after OA commit",
        rt: "status: active · op: outcome_unknown",
        ext: "applications: 1 (committed in OA, response lost)"
      },
      {
        cmd: "reconcile(operation_id) → lookup by business_key",
        rt: "status: active · op: confirmed_succeeded",
        ext: "applications: 1 (recovered, 0 duplicate calls)"
      },
      {
        cmd: "request_completion() → match receipt & verified proof",
        rt: "status: closed · outcome: succeeded",
        ext: "applications: 1 (verified end-to-end closure)"
      }
    ]
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
   * current stage and adds Prev/Next + arrow-key controls + stage inspector. */
  var stages = Array.prototype.slice.call(
    document.querySelectorAll("#recovery-stages .stage"));
  if (stages.length) {
    var total = stages.length;
    var index = 0;
    stages.forEach(function (stage, i) {
      stage.dataset.stage = String(i + 1);
      stage.addEventListener("click", function () { goTo(i); });
    });

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

    var list = stages[0].parentElement;
    list.parentElement.insertBefore(controls, list);
    list.tabIndex = 0;
    list.setAttribute("aria-label", MSG.stages);

    var inspector = document.createElement("div");
    inspector.className = "stage-inspector";
    var cellCmd = document.createElement("div");
    cellCmd.className = "inspector-cell";
    var lblCmd = document.createElement("div");
    lblCmd.className = "inspector-label";
    lblCmd.textContent = MSG.lblCommand;
    var valCmd = document.createElement("div");
    valCmd.className = "inspector-value";
    cellCmd.appendChild(lblCmd);
    cellCmd.appendChild(valCmd);

    var cellRt = document.createElement("div");
    cellRt.className = "inspector-cell";
    var lblRt = document.createElement("div");
    lblRt.className = "inspector-label";
    lblRt.textContent = MSG.lblRuntime;
    var valRt = document.createElement("div");
    valRt.className = "inspector-value";
    cellRt.appendChild(lblRt);
    cellRt.appendChild(valRt);

    var cellExt = document.createElement("div");
    cellExt.className = "inspector-cell";
    var lblExt = document.createElement("div");
    lblExt.className = "inspector-label";
    lblExt.textContent = MSG.lblExternal;
    var valExt = document.createElement("div");
    valExt.className = "inspector-value";
    cellExt.appendChild(lblExt);
    cellExt.appendChild(valExt);

    inspector.appendChild(cellCmd);
    inspector.appendChild(cellRt);
    inspector.appendChild(cellExt);
    list.parentElement.insertBefore(inspector, list.nextSibling);

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
      var snap = MSG.snapshots[index] || MSG.snapshots[0];
      valCmd.textContent = snap.cmd;
      valRt.textContent = snap.rt;
      valExt.textContent = snap.ext;
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
