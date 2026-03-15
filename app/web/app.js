const apiBase = "";

const chatLog = document.getElementById("chatLog");
const chatForm = document.getElementById("chatForm");
const chatInput = document.getElementById("chatInput");
const clearChat = document.getElementById("clearChat");

const dayScheduleGrid = document.getElementById("dayScheduleGrid");
const weekScheduleGrid = document.getElementById("weekScheduleGrid");

const actionDateInput = document.getElementById("actionDateInput");
const weekStartInput = document.getElementById("weekStartInput");
const reoptimize = document.getElementById("reoptimize");

const loadDayBtn = document.getElementById("loadDayBtn");
const autofillBtn = document.getElementById("autofillBtn");
const loadWeekBtn = document.getElementById("loadWeekBtn");
const thisWeekBtn = document.getElementById("thisWeekBtn");

const dayTabBtn = document.getElementById("dayTabBtn");
const weekTabBtn = document.getElementById("weekTabBtn");
const dayView = document.getElementById("dayView");
const weekView = document.getElementById("weekView");

const healthStatus = document.getElementById("healthStatus");
const apiBaseLabel = document.getElementById("apiBase");
const changeSummary = document.getElementById("changeSummary");

apiBaseLabel.textContent = apiBase || "/";

const SHIFT_TYPES = ["LUNCH", "DINNER"];
const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const fmtDate = (value) => {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
};
const toDate = (value) => new Date(`${value}T00:00:00`);
const addDays = (value, amount) => {
  const date = new Date(value);
  date.setDate(date.getDate() + amount);
  return date;
};

const getWeekStart = (value) => {
  const date = toDate(value);
  const day = date.getDay();
  const offset = day === 0 ? -6 : 1 - day;
  return fmtDate(addDays(date, offset));
};

const getWeekDates = (weekStart) => {
  const start = toDate(weekStart);
  return Array.from({ length: 7 }, (_, index) => fmtDate(addDays(start, index)));
};

const shiftKey = (date, shiftType) => `${date}__${shiftType}`;
const buildShiftFingerprint = (shift) => {
  const assignments = [...(shift.assignments || [])]
    .map((item) => `${item.role_name}:${item.employee_name || "UNASSIGNED"}`)
    .sort();
  return assignments.join("|");
};

let currentWeekStart = null;
let currentWeekShiftMap = new Map();
let currentDayShiftMap = new Map();
let activeTab = "day";

const today = new Date();
const todayStr = fmtDate(today);
if (actionDateInput) {
  actionDateInput.value = todayStr;
}
if (weekStartInput) {
  weekStartInput.value = getWeekStart(todayStr);
}

const appendMessage = (role, text) => {
  const msg = document.createElement("div");
  msg.className = `message ${role}`;
  msg.textContent = text;
  chatLog.appendChild(msg);
  chatLog.scrollTop = chatLog.scrollHeight;
};

const fetchJson = async (url, options = {}) => {
  const response = await fetch(`${apiBase}${url}`, options);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || "Request failed");
  }
  return response.json();
};

const summarizeResponse = (payload) => {
  if (!payload) return "Done.";
  if (payload.action_type === "AUTOFILL_DAY") {
    const dateResults = payload.result?.dates || [];
    if (dateResults.length > 0) {
      return dateResults
        .map((entry) => {
          const dateLabel = entry.date || "unknown-date";
          const shifts = entry.results || [];
          const created = shifts.reduce((sum, item) => sum + (item.created || 0), 0);
          return `${dateLabel}: ${created} filled`;
        })
        .join(" | ");
    }

    const results = payload.result?.results || [];
    return results
      .map((item) => `${item.shift_type}: ${item.created} filled`)
      .join(" | ");
  }
  if (payload.action_type === "SWAP_ASSIGNMENT") {
    return `Swap applied (old: ${payload.result?.old_employee_id}, new: ${payload.result?.new_employee_id}).`;
  }
  if (payload.action_type === "SET_RULE") {
    return "Rule updated.";
  }
  return "Done.";
};

const switchTab = (tab) => {
  activeTab = tab;

  if (tab === "day") {
    dayView.classList.remove("hidden");
    weekView.classList.add("hidden");
    dayTabBtn.classList.add("active");
    weekTabBtn.classList.remove("active");
  } else {
    weekView.classList.remove("hidden");
    dayView.classList.add("hidden");
    weekTabBtn.classList.add("active");
    dayTabBtn.classList.remove("active");
  }
};

const renderDaySchedule = (shifts, changedShiftTypes = new Set()) => {
  dayScheduleGrid.innerHTML = "";

  const actionDate = actionDateInput?.value;
  if (!actionDate) {
    dayScheduleGrid.innerHTML = "<p>Select a date to load schedule data.</p>";
    return;
  }

  const byType = new Map((shifts || []).map((shift) => [shift.shift_type, shift]));

  SHIFT_TYPES.forEach((type) => {
    const shift = byType.get(type) || {
      date: actionDate,
      shift_type: type,
      assignments: [],
    };

    const card = document.createElement("div");
    card.className = "shift-card";
    if (changedShiftTypes.has(type)) {
      card.classList.add("changed");
    }

    const header = document.createElement("div");
    header.className = "shift-header";
    header.innerHTML = `<strong>${shift.date}</strong><span class="shift-tag">${shift.shift_type}</span>`;
    card.appendChild(header);

    if (!shift.assignments || shift.assignments.length === 0) {
      const empty = document.createElement("div");
      empty.className = "assignment";
      empty.innerHTML = `<span class="role">No assignments</span><span class="employee">-</span>`;
      card.appendChild(empty);
    } else {
      const list = document.createElement("div");
      shift.assignments.forEach((item) => {
        const row = document.createElement("div");
        row.className = "assignment";
        row.innerHTML = `
          <span class="role">${item.role_name}</span>
          <span class="employee">${item.employee_name || "Unassigned"}</span>
        `;
        list.appendChild(row);
      });
      card.appendChild(list);
    }

    dayScheduleGrid.appendChild(card);
  });
};

const renderWeekSchedule = (shifts, changedKeys = new Set()) => {
  weekScheduleGrid.innerHTML = "";
  if (!currentWeekStart) {
    weekScheduleGrid.innerHTML = "<p>Select a week to load schedule data.</p>";
    return;
  }

  const byKey = new Map(
    (shifts || []).map((shift) => [shiftKey(shift.date, shift.shift_type), shift])
  );
  const weekDates = getWeekDates(currentWeekStart);

  weekDates.forEach((date, index) => {
    const dayColumn = document.createElement("div");
    dayColumn.className = "day-column";

    const header = document.createElement("div");
    header.className = "day-header";
    header.innerHTML = `
      <div class="day-name">${DAY_LABELS[index]}</div>
      <div class="day-date">${date}</div>
    `;
    dayColumn.appendChild(header);

    SHIFT_TYPES.forEach((type) => {
      const key = shiftKey(date, type);
      const shift = byKey.get(key) || { date, shift_type: type, assignments: [] };

      const card = document.createElement("div");
      card.className = "shift-card";
      if (changedKeys.has(key)) {
        card.classList.add("changed");
      }

      const shiftHeader = document.createElement("div");
      shiftHeader.className = "shift-header";
      shiftHeader.innerHTML = `<span class="shift-tag">${shift.shift_type}</span>`;
      card.appendChild(shiftHeader);

      if (!shift.assignments || shift.assignments.length === 0) {
        const empty = document.createElement("div");
        empty.className = "assignment";
        empty.innerHTML = `<span class="role">No assignments</span><span class="employee">-</span>`;
        card.appendChild(empty);
      } else {
        const list = document.createElement("div");
        shift.assignments.forEach((item) => {
          const row = document.createElement("div");
          row.className = "assignment";
          row.innerHTML = `
            <span class="role">${item.role_name}</span>
            <span class="employee">${item.employee_name || "Unassigned"}</span>
          `;
          list.appendChild(row);
        });
        card.appendChild(list);
      }

      dayColumn.appendChild(card);
    });

    weekScheduleGrid.appendChild(dayColumn);
  });
};

const fetchDaySchedule = async (date) => {
  return fetchJson(`/schedules?start_date=${date}&end_date=${date}`);
};

const fetchWeekSchedule = async (weekStart) => {
  const weekDates = getWeekDates(weekStart);
  const endDate = weekDates[weekDates.length - 1];
  return fetchJson(`/schedules?start_date=${weekStart}&end_date=${endDate}`);
};

const buildWeekShiftMap = (shifts) => {
  const map = new Map();
  (shifts || []).forEach((shift) => {
    map.set(shiftKey(shift.date, shift.shift_type), buildShiftFingerprint(shift));
  });
  return map;
};

const buildDayShiftMap = (shifts) => {
  const map = new Map();
  (shifts || []).forEach((shift) => {
    map.set(shift.shift_type, buildShiftFingerprint(shift));
  });
  return map;
};

const diffMaps = (beforeMap, afterMap) => {
  const keys = new Set([...beforeMap.keys(), ...afterMap.keys()]);
  const changed = new Set();
  keys.forEach((key) => {
    if ((beforeMap.get(key) || "") !== (afterMap.get(key) || "")) {
      changed.add(key);
    }
  });
  return changed;
};

const describeChangedShifts = (changedKeys) => {
  if (!changedKeys || changedKeys.size === 0) {
    return "No schedule changes detected in the selected week.";
  }

  const labels = [...changedKeys]
    .sort()
    .map((key) => {
      const [date, shiftType] = key.split("__");
      return `${date} ${shiftType}`;
    });

  return `Updated shifts: ${labels.join(", ")}`;
};

const refreshDaySchedule = async (changedShiftTypes = new Set()) => {
  const actionDate = actionDateInput?.value;
  if (!actionDate) {
    return;
  }

  const schedule = await fetchDaySchedule(actionDate);
  currentDayShiftMap = buildDayShiftMap(schedule);
  renderDaySchedule(schedule, changedShiftTypes);
};

const refreshWeekSchedule = async (changedKeys = new Set()) => {
  if (!currentWeekStart) {
    return;
  }

  const schedule = await fetchWeekSchedule(currentWeekStart);
  currentWeekShiftMap = buildWeekShiftMap(schedule);
  renderWeekSchedule(schedule, changedKeys);
  if (changeSummary) {
    changeSummary.textContent = describeChangedShifts(changedKeys);
  }
};

const runChatCommand = async (message, action = null) => {
  const beforeWeekMap = new Map(currentWeekShiftMap);
  const beforeDayMap = new Map(currentDayShiftMap);
  const beforeDayDate = actionDateInput?.value || null;

  const payload = { message };
  if (action) {
    payload.action = action;
  }

  const response = await fetchJson("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  appendMessage("system", summarizeResponse(response));

  if (response.action_type === "AUTOFILL_DAY") {
    const targetDate = action?.date || response.result?.date;
    if (targetDate) {
      if (actionDateInput) {
        actionDateInput.value = targetDate;
      }
      if (weekStartInput) {
        weekStartInput.value = getWeekStart(targetDate);
        currentWeekStart = weekStartInput.value;
      }
    }
  }

  await refreshDaySchedule();
  await refreshWeekSchedule();

  const changedWeekKeys = diffMaps(beforeWeekMap, currentWeekShiftMap);
  let changedDayTypes = new Set();
  if (beforeDayDate && beforeDayDate === actionDateInput?.value) {
    changedDayTypes = diffMaps(beforeDayMap, currentDayShiftMap);
  }

  await refreshDaySchedule(changedDayTypes);
  await refreshWeekSchedule(changedWeekKeys);
};

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = chatInput.value.trim();
  if (!text) return;

  appendMessage("user", text);
  chatInput.value = "";

  try {
    await runChatCommand(text);
  } catch (error) {
    appendMessage("system", `Error: ${error.message}`);
  }
});

clearChat.addEventListener("click", () => {
  chatLog.innerHTML = "";
});

loadDayBtn.addEventListener("click", async () => {
  try {
    await refreshDaySchedule();
  } catch (error) {
    appendMessage("system", `Error: ${error.message}`);
  }
});

autofillBtn.addEventListener("click", async () => {
  const value = actionDateInput.value;
  if (!value) return;

  const action = {
    type: "AUTOFILL_DAY",
    date: value,
    reoptimize: Boolean(reoptimize.checked),
  };

  appendMessage("user", `autofill ${value}`);
  try {
    await runChatCommand(`autofill ${value}`, action);
  } catch (error) {
    appendMessage("system", `Error: ${error.message}`);
  }
});

loadWeekBtn.addEventListener("click", async () => {
  try {
    if (weekStartInput?.value) {
      currentWeekStart = getWeekStart(weekStartInput.value);
      weekStartInput.value = currentWeekStart;
      await refreshWeekSchedule();
    }
  } catch (error) {
    appendMessage("system", `Error: ${error.message}`);
  }
});

thisWeekBtn.addEventListener("click", async () => {
  const now = fmtDate(new Date());
  const newWeekStart = getWeekStart(now);

  if (actionDateInput) {
    actionDateInput.value = now;
  }
  if (weekStartInput) {
    weekStartInput.value = newWeekStart;
  }
  currentWeekStart = newWeekStart;

  try {
    await refreshDaySchedule();
    await refreshWeekSchedule();
  } catch (error) {
    appendMessage("system", `Error: ${error.message}`);
  }
});

dayTabBtn.addEventListener("click", () => switchTab("day"));
weekTabBtn.addEventListener("click", () => switchTab("week"));

const checkHealth = async () => {
  try {
    await fetchJson("/health");
    healthStatus.textContent = "API online";
  } catch {
    healthStatus.textContent = "API offline";
  }
};

checkHealth();
switchTab(activeTab);
currentWeekStart = weekStartInput?.value || getWeekStart(todayStr);
refreshDaySchedule();
refreshWeekSchedule();
