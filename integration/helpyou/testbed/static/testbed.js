(() => {
  const state = { sessionId: null, snapshot: null, mode: 'flight_scenario' };
  const $ = (id) => document.getElementById(id);

  const escapeHtml = (value) => String(value ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#039;');

  function toast(message) {
    const node = $('toast');
    node.textContent = message;
    node.classList.remove('hidden');
    clearTimeout(node._timer);
    node._timer = setTimeout(() => node.classList.add('hidden'), 3200);
  }

  async function api(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    });
    if (!response.ok) {
      let detail = response.statusText;
      try { detail = (await response.json()).detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    return response.json();
  }

  function setMode(mode) {
    state.mode = mode;
    $('mode').value = mode;
    document.querySelectorAll('.mode-tab').forEach((button) => {
      button.classList.toggle('active', button.dataset.mode === mode);
    });
    const scenario = $('scenario');
    const caseLabel = $('case-label');
    if (mode === 'flight_scenario') {
      caseLabel.classList.remove('hidden');
      scenario.value = 'Stable one-engine-inoperative condition at ETP1-1D. Compare the Flight Briefing candidates CYQX and EINN and explain the decision gate.';
    } else {
      caseLabel.classList.add('hidden');
      scenario.value = 'Describe the flight-related experience, correction, technique or source reference you want Helpyou to learn.';
    }
  }

  function renderSessions(items) {
    const container = $('session-list');
    container.innerHTML = items.map((item) => `
      <button class="session-item ${item.id === state.sessionId ? 'active' : ''}" data-session-id="${escapeHtml(item.id)}">
        <strong>${escapeHtml(item.case_id || 'Pilot contribution')}</strong>
        <span>${escapeHtml(item.scenario.slice(0, 82))}</span>
        <small>${escapeHtml(item.status)} · ${escapeHtml(item.updated_at)}</small>
      </button>`).join('') || '<p class="muted small">No sessions yet.</p>';
    container.querySelectorAll('.session-item').forEach((button) => {
      button.addEventListener('click', () => loadSession(button.dataset.sessionId));
    });
  }

  async function refreshSessions() {
    const data = await api('/api/sessions');
    renderSessions(data.sessions);
  }

  function renderMessages(messages) {
    const node = $('messages');
    node.innerHTML = messages.map((message) => `
      <div class="message message-${escapeHtml(message.role)}">
        ${escapeHtml(message.content)}
        <small>${escapeHtml(message.kind.replaceAll('_', ' '))} · ${escapeHtml(message.created_at)}</small>
      </div>`).join('') || '<p class="muted small">The guided transcript will appear here.</p>';
    node.scrollTop = node.scrollHeight;
  }

  function renderBaseline(baseline) {
    const node = $('baseline-summary');
    if (!baseline) {
      $('snapshot-badge').textContent = 'Not loaded';
      $('snapshot-badge').className = 'status-badge neutral';
      node.innerHTML = 'This session captures pilot knowledge and does not load flight-specific data.';
      return;
    }
    $('snapshot-badge').textContent = 'Loaded';
    $('snapshot-badge').className = 'status-badge';
    node.innerHTML = `
      <div class="baseline-row"><strong>Flight</strong><span>${escapeHtml(baseline.flight_number)} · ${escapeHtml(baseline.route)}</span></div>
      <div class="baseline-row"><strong>Aircraft</strong><span>${escapeHtml(baseline.aircraft)} · ${escapeHtml(baseline.registration)}</span></div>
      <div class="baseline-row"><strong>Anchor</strong><span>${escapeHtml(baseline.anchor.waypoint)} · ACTM ${escapeHtml(baseline.anchor.actm)} · ${escapeHtml(baseline.anchor.utc)}</span></div>
      <div class="baseline-row"><strong>Phase</strong><span>${escapeHtml(baseline.anchor.phase)}</span></div>
      <div class="baseline-row"><strong>Snapshot</strong><span>${escapeHtml(baseline.source_snapshot_id)}</span></div>
      <details><summary>Golden-test assumptions</summary><ul class="assumption-list">${baseline.assumptions.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul></details>`;
  }

  function renderOptions(options) {
    const node = $('option-cards');
    node.innerHTML = options.map((option) => `
      <article class="option-card ${escapeHtml(option.state)}">
        <header><h3>${escapeHtml(option.id)}</h3><span class="status-badge">${escapeHtml(option.state.replaceAll('_', ' '))}</span></header>
        <div class="option-metrics">
          ${option.distance_nm ? `<span>${escapeHtml(option.distance_nm)} NM</span>` : ''}
          ${option.diversion_time ? `<span>${escapeHtml(option.diversion_time)}</span>` : ''}
          ${option.planned_level ? `<span>FL${escapeHtml(option.planned_level)}</span>` : ''}
        </div>
        ${option.weather ? `<p><strong>Weather:</strong> ${escapeHtml(option.weather.summary)}</p>` : ''}
        <details><summary>Conditions and residual risks</summary>
          <ul>${option.conditions.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>
          <ul>${option.residual_risks.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>
        </details>
      </article>`).join('') || '<p class="muted small">No flight-specific option cards in this mode.</p>';
  }

  function renderMemory(memories) {
    const node = $('memory-cards');
    node.innerHTML = memories.map((memory) => `
      <article class="memory-card">
        <header><h3>${escapeHtml(memory.record_type.replaceAll('_', ' '))}</h3><button data-memory-id="${memory.id}" type="button">Delete</button></header>
        <p class="raw">${escapeHtml(memory.raw_pilot_wording)}</p>
        <p class="interpretation"><strong>Helpyou understood:</strong> ${escapeHtml(memory.ai_interpretation)}</p>
        <small>${escapeHtml(memory.evidence_status)} · ${escapeHtml(memory.privacy_scope)}</small>
      </article>`).join('') || '<p class="muted small">No durable pilot memory has been stored in this session.</p>';
    node.querySelectorAll('button[data-memory-id]').forEach((button) => {
      button.addEventListener('click', async () => {
        if (!confirm('Delete this memory record?')) return;
        try {
          const snapshot = await api(`/api/sessions/${state.sessionId}/memories/${button.dataset.memoryId}`, { method: 'DELETE' });
          renderSnapshot(snapshot);
        } catch (error) { toast(error.message); }
      });
    });
  }

  function fieldHtml(field) {
    if (field.type === 'options') {
      return `<fieldset><legend>${escapeHtml(field.label)}</legend><div class="option-choice-grid">${field.options.map((option, index) => `
        <div class="option-choice"><input type="radio" id="choice-${index}" name="${escapeHtml(field.name)}" value="${escapeHtml(option.value)}" required>
        <label for="choice-${index}"><strong>${escapeHtml(option.value)}</strong><small>${escapeHtml(option.state.replaceAll('_', ' '))}</small></label></div>`).join('')}</div></fieldset>`;
    }
    if (field.type === 'textarea') {
      return `<label>${escapeHtml(field.label)}<textarea name="${escapeHtml(field.name)}" rows="4" placeholder="${escapeHtml(field.placeholder || '')}"></textarea></label>`;
    }
    return `<label>${escapeHtml(field.label)}<input name="${escapeHtml(field.name)}" type="${escapeHtml(field.type || 'text')}" placeholder="${escapeHtml(field.placeholder || '')}"></label>`;
  }

  function renderQuestion(question, phase) {
    const card = $('question-card');
    if (!question) { card.classList.add('hidden'); return; }
    card.classList.remove('hidden');
    $('question-key').value = question.key;
    $('question-model').textContent = question.model;
    $('question-title').textContent = question.title;
    $('question-prompt').textContent = question.prompt;
    $('question-progress').textContent = phase.replaceAll('_', ' ');
    const why = $('question-why');
    if (question.why_it_matters) { why.textContent = question.why_it_matters; why.classList.remove('hidden'); }
    else { why.classList.add('hidden'); }
    $('question-fields').innerHTML = question.fields.map(fieldHtml).join('');
  }

  function compactCitation(citation) {
    const parts = [citation.owner, citation.document];
    if (citation.revision) parts.push(citation.revision);
    if (citation.eff) parts.push(`eff ${citation.eff}`);
    if (citation.section) parts.push(citation.section);
    if (citation.page) parts.push(String(citation.page).startsWith('p') ? citation.page : `p.${citation.page}`);
    return `[${parts.join(' | ')}]`;
  }

  function renderTeaching(plan) {
    const card = $('teaching-card');
    if (!plan) { card.classList.add('hidden'); return; }
    card.classList.remove('hidden');
    $('teaching-status').textContent = plan.status.replaceAll('_', ' ');
    $('teaching-headline').textContent = plan.headline;
    $('teaching-answer').textContent = plan.answer;
    $('teaching-sa').textContent = plan.key_sa_point || 'No material situational-awareness gap remains in the stated discussion.';
    $('teaching-cognitive').textContent = plan.key_cognitive_point || 'No material operational-model gap remains in the stated discussion.';
    const gate = $('teaching-decision-gate');
    if (plan.decision_gate) { gate.textContent = `Decision gate: ${plan.decision_gate}`; gate.classList.remove('hidden'); }
    else { gate.classList.add('hidden'); }
    $('developmental-points').innerHTML = plan.developmental_points.map((item) => `<div class="developmental-point">${escapeHtml(item)}</div>`).join('');
    $('teaching-conditions').innerHTML = `<h3>Conditions</h3><ul>${plan.conditions.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`;
    $('teaching-citations').innerHTML = `<h3>References</h3>${plan.citations.map((item) => `<span class="source-chip">${escapeHtml(compactCitation(item))}</span>`).join('')}`;
  }

  function renderSnapshot(snapshot) {
    state.snapshot = snapshot;
    state.sessionId = snapshot.session.id;
    $('empty-state').classList.add('hidden');
    $('session-workspace').classList.remove('hidden');
    $('session-mode-label').textContent = snapshot.session.mode === 'flight_scenario' ? 'CFP-grounded scenario' : 'Pilot contribution';
    $('session-title').textContent = snapshot.session.case_id || 'Teach Helpyou';
    $('session-scenario').textContent = snapshot.session.scenario;
    $('export-session').href = `/api/sessions/${state.sessionId}/export`;
    renderMessages(snapshot.messages || []);
    renderBaseline(snapshot.baseline);
    renderOptions(snapshot.options || []);
    renderMemory(snapshot.memory || []);
    renderQuestion(snapshot.question, snapshot.phase);
    renderTeaching(snapshot.teaching_plan);
    $('teach-card').classList.toggle('hidden', snapshot.session.mode !== 'teach_helpyou');
    refreshSessions().catch(() => {});
  }

  async function loadSession(sessionId) {
    try {
      renderSnapshot(await api(`/api/sessions/${sessionId}`));
    } catch (error) { toast(error.message); }
  }

  document.querySelectorAll('.mode-tab').forEach((button) => {
    button.addEventListener('click', () => setMode(button.dataset.mode));
  });

  $('new-session-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      const payload = {
        mode: $('mode').value,
        case_id: $('mode').value === 'flight_scenario' ? $('case-id').value : null,
        scenario: $('scenario').value,
      };
      renderSnapshot(await api('/api/sessions', { method: 'POST', body: JSON.stringify(payload) }));
    } catch (error) { toast(error.message); }
  });

  $('answer-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = new FormData(event.target);
    const values = {};
    for (const [key, value] of form.entries()) values[key] = value;
    try {
      const snapshot = await api(`/api/sessions/${state.sessionId}/answer`, {
        method: 'POST',
        body: JSON.stringify({ question_key: $('question-key').value, values }),
      });
      renderSnapshot(snapshot);
    } catch (error) { toast(error.message); }
  });

  $('teach-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      const snapshot = await api(`/api/sessions/${state.sessionId}/teach`, {
        method: 'POST',
        body: JSON.stringify({
          record_type: $('teach-record-type').value,
          raw_pilot_wording: $('teach-raw').value,
          context: $('teach-context').value,
          privacy_scope: $('teach-privacy').value,
        }),
      });
      $('teach-raw').value = '';
      $('teach-context').value = '';
      renderSnapshot(snapshot);
      toast('Pilot contribution stored with raw wording and separate interpretation.');
    } catch (error) { toast(error.message); }
  });

  $('reset-session').addEventListener('click', async () => {
    if (!state.sessionId || !confirm('Reset this test session and remove its transcript and memory?')) return;
    try { renderSnapshot(await api(`/api/sessions/${state.sessionId}/reset`, { method: 'POST' })); }
    catch (error) { toast(error.message); }
  });
  $('refresh-sessions').addEventListener('click', () => refreshSessions().catch((error) => toast(error.message)));
  document.querySelectorAll('.session-item').forEach((button) => button.addEventListener('click', () => loadSession(button.dataset.sessionId)));
})();
