// === STATE ===
let chatHistory = [];
let currentStage = "idle";
let currentFormData = {};

// === DOM ===
const chatMessages = document.getElementById("chatMessages");
const chatInput = document.getElementById("chatInput");
const sendBtn = document.getElementById("sendBtn");
const exportCsvBtn = document.getElementById("exportCsvBtn");
const formContent = document.getElementById("formContent");
const stageBadge = document.getElementById("stageBadge");

// === QUICK COMMANDS ===
document.querySelectorAll(".quick-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    chatInput.value = btn.dataset.cmd;
    sendMessage();
  });
});

// === SEND ===
sendBtn.addEventListener("click", sendMessage);
chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

async function sendMessage() {
  const text = chatInput.value.trim();
  if (!text) return;

  addMessageToUI("user", text);
  chatHistory.push({ role: "user", content: text });
  chatInput.value = "";

  const loadingId = addTypingIndicator();

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        history: chatHistory,
        stage: currentStage,
        product_code: currentFormData.product_code,
        quantity: currentFormData.quantity,
        total_base: currentFormData.total_base,
      }),
    });
    const data = await response.json();

    document.getElementById(loadingId)?.remove();

    const sourceTag = data.source === "local" ? "⚡" : "🤖";
    addMessageToUI("ai", `${sourceTag} ${data.reply}`);
    chatHistory.push({ role: "assistant", content: data.reply });

    // Update stage
    if (data.stage) currentStage = data.stage;
    if (data.form_data) {
      currentFormData = { ...currentFormData, ...data.form_data };
      renderForm(data.form_data);
    }
    updateStageBadge(currentStage);
  } catch (error) {
    document.getElementById(loadingId)?.remove();
    addMessageToUI("ai", "⚠️ Ошибка соединения. Попробуйте позже.");
  }
}

function addMessageToUI(role, text) {
  const div = document.createElement("div");
  div.className = `message ${role}`;
  const avatar = role === "ai" ? "🤖" : "👤";
  div.innerHTML = `
        <div class="msg-avatar">${avatar}</div>
        <div class="msg-body">${escapeHtml(text)}</div>
    `;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function addTypingIndicator() {
  const div = document.createElement("div");
  div.className = "message ai";
  div.id = "typing-" + Date.now();
  div.innerHTML = `
        <div class="msg-avatar">🤖</div>
        <div class="msg-body">
            <div class="typing-indicator"><span></span><span></span><span></span></div>
        </div>
    `;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return div.id;
}

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\n/g, "<br>");
}

// === FORM RENDER ===
function renderForm(data) {
  if (!data || !data.type) return;

  switch (data.type) {
    case "request_form":
      formContent.innerHTML = renderRequestForm(data);
      attachConfirmHandler(data);
      break;
    case "cost_calc":
      formContent.innerHTML = renderCostCalc(data);
      attachMarginHandler(data);
      break;
    case "final_result":
      formContent.innerHTML = renderFinalResult(data);
      break;
  }
}

function renderRequestForm(d) {
  return `
        <div class="doc-card">
            <div class="doc-card-header">
                <div class="doc-card-title">📝 Заказ покупателя (черновик)</div>
                <span class="doc-card-badge badge-new">Новая заявка</span>
            </div>
            <div class="doc-row"><span class="label">Клиент:</span><span class="value">${d.client}</span></div>
            <div class="doc-row"><span class="label">Товар:</span><span class="value">${d.product_name}</span></div>
            <div class="doc-row"><span class="label">Код:</span><span class="value">${d.product_code}</span></div>
            <div class="doc-row"><span class="label">Количество:</span><span class="value">${d.quantity} шт</span></div>
            <div class="doc-row"><span class="label">Срок отгрузки:</span><span class="value">${d.deadline}</span></div>
            <div class="doc-total">
                <span>Базовая цена:</span>
                <span>${d.total_base.toLocaleString("ru-RU")} ₽</span>
            </div>
            <div class="doc-actions">
                <button class="btn-primary" id="confirmBtn">✅ Подтвердить и запросить себестоимость</button>
                <button class="btn-secondary" id="cancelBtn">Отмена</button>
            </div>
        </div>
    `;
}

function renderCostCalc(d) {
  return `
        <div class="doc-card">
            <div class="doc-card-header">
                <div class="doc-card-title">💰 Расчёт себестоимости</div>
                <span class="doc-card-badge badge-progress">От технолога</span>
            </div>
            <div class="doc-row"><span class="label">Изделие:</span><span class="value">${d.product_code}</span></div>
            <div class="doc-row"><span class="label">Количество:</span><span class="value">${d.quantity} шт</span></div>
            <div class="doc-row"><span class="label">🔩 Материалы:</span><span class="value">${d.materials.toLocaleString("ru-RU")} ₽</span></div>
            <div class="doc-row"><span class="label">👷 Труд:</span><span class="value">${d.labor.toLocaleString("ru-RU")} ₽</span></div>
            <div class="doc-row"><span class="label">🏢 Накладные:</span><span class="value">${d.overhead.toLocaleString("ru-RU")} ₽</span></div>
            <div class="doc-total">
                <span>Итого себестоимость:</span>
                <span>${d.total_cost.toLocaleString("ru-RU")} ₽</span>
            </div>
            <div style="font-size: 11px; color: var(--text-muted); margin-top: 8px; text-align: right;">
                Рассчитал: ${d.engineer}
            </div>
            <div class="doc-actions">
                <button class="btn-primary" id="marginBtn">📊 Рассчитать маржинальность</button>
            </div>
        </div>
    `;
}

function renderFinalResult(d) {
  const isWarning = d.margin < 30;
  return `
        <div class="doc-card result-card ${isWarning ? "warning" : ""}">
            <div class="doc-card-header">
                <div class="doc-card-title">🎯 Итоговый расчёт заказа</div>
                <span class="doc-card-badge ${d.status === "approved" ? "badge-done" : "badge-progress"}">
                    ${d.status === "approved" ? "✅ К отправке" : "⚠️ На согласовании"}
                </span>
            </div>
            <div class="metric-grid">
                <div class="metric">
                    <div class="metric-value">${d.revenue.toLocaleString("ru-RU")} ₽</div>
                    <div class="metric-label">Выручка</div>
                </div>
                <div class="metric">
                    <div class="metric-value">${d.cost.toLocaleString("ru-RU")} ₽</div>
                    <div class="metric-label">Себестоимость</div>
                </div>
                <div class="metric">
                    <div class="metric-value">${d.profit.toLocaleString("ru-RU")} ₽</div>
                    <div class="metric-label">Прибыль</div>
                </div>
                <div class="metric">
                    <div class="metric-value">${d.margin}%</div>
                    <div class="metric-label">Маржинальность</div>
                </div>
            </div>
            <div class="doc-actions" style="margin-top: 20px;">
                <button class="btn-primary" onclick="alert('📬 Заказ отправлен в производство!\\nСоздан Заказ на производство для инженера ПДО.')">
                    🚀 Передать в производство
                </button>
                <button class="btn-secondary" onclick="location.reload()">Новая заявка</button>
            </div>
        </div>
    `;
}

function attachConfirmHandler(data) {
  document.getElementById("confirmBtn")?.addEventListener("click", () => {
    chatInput.value = "Да, подтверждаю заявку";
    sendMessage();
  });
  document.getElementById("cancelBtn")?.addEventListener("click", () => {
    addMessageToUI("user", "Отменить заявку");
    chatHistory.push({ role: "user", content: "Отменить заявку" });
    addMessageToUI("ai", "⚡ Заявка отменена. Готов к новой!");
    chatHistory.push({
      role: "assistant",
      content: "Заявка отменена. Готов к новой!",
    });
    currentStage = "idle";
    currentFormData = {};
    updateStageBadge("idle");
    formContent.innerHTML = `
            <div class="placeholder-card">
                <div class="placeholder-icon">📄</div>
                <div class="placeholder-title">Ожидание заявки</div>
                <div class="placeholder-text">Начните диалог с AI-ассистентом.</div>
            </div>`;
  });
}

function attachMarginHandler(data) {
  document.getElementById("marginBtn")?.addEventListener("click", () => {
    chatInput.value = "Рассчитай маржу";
    sendMessage();
  });
}

function updateStageBadge(stage) {
  const labels = {
    idle: ["● Готов к работе", "#10B981", "#ECFDF5"],
    awaiting_confirmation: ["● Ожидает подтверждения", "#F59E0B", "#FEF3C7"],
    cost_ready: ["● Себестоимость получена", "#3B82F6", "#DBEAFE"],
    final: ["● Заказ оформлен", "#10B981", "#D1FAE5"],
  };
  const [text, color, bg] = labels[stage] || labels["idle"];
  stageBadge.textContent = text;
  stageBadge.style.color = color;
  stageBadge.style.background = bg;
}

// === CSV EXPORT ===
exportCsvBtn.addEventListener("click", () => {
  if (chatHistory.length === 0) {
    alert("Чат пуст");
    return;
  }
  let csv = "\uFEFFRole,Message,Timestamp\n";
  chatHistory.forEach((msg) => {
    const escaped = `"${msg.content.replace(/"/g, '""').replace(/\n/g, " ")}"`;
    csv += `${msg.role},${escaped},${new Date().toISOString()}\n`;
  });
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `sales_agent_chat_${Date.now()}.csv`;
  link.click();
});
