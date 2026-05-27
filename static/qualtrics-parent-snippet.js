/**
 * Qualtrics parent-page script — paste INLINE into the chat HTML question.
 * Saves transcript + chat_status when chat ends OR when participant clicks Next early.
 */
(function () {
  var MAX_TRANSCRIPT_CHARS = 240000;
  var API_BASE = 'https://group.xjhuang.com';

  function saveActr(data) {
    if (!data || data.source !== 'ACTR_CHAT' || data.event !== 'chat_ended') {
      return false;
    }
    var se = window.Qualtrics && window.Qualtrics.SurveyEngine;
    if (!se) {
      console.warn('[ACTR] Qualtrics.SurveyEngine not available');
      return false;
    }

    var transcriptField = data.qualtrics_field_transcript || 'transcript';
    var statusField = data.qualtrics_field_status || 'chat_status';
    var text = data.transcript_text != null ? String(data.transcript_text) : '';
    if (text.length > MAX_TRANSCRIPT_CHARS) {
      text = text.slice(0, MAX_TRANSCRIPT_CHARS) + '\n...(truncated)';
    }

    se.setEmbeddedData(statusField, data.chat_status || 'unknown');
    se.setEmbeddedData(transcriptField, text);
    window.__actrSaved = true;

    console.log('[ACTR] saved', statusField, '=', data.chat_status, '|', transcriptField, text.length, 'chars');

    if (data.auto_advance && se.clickNextButton) {
      se.clickNextButton();
    }
    return true;
  }

  function getChatIframe() {
    return document.querySelector('iframe[src*="embed.html"]');
  }

  function getApiBase() {
    var iframe = getChatIframe();
    if (!iframe || !iframe.src) return API_BASE;
    try {
      return new URL(iframe.src).origin;
    } catch (e) {
      return API_BASE;
    }
  }

  function parseIframeParams() {
    var iframe = getChatIframe();
    if (!iframe || !iframe.src) return null;
    try {
      var u = new URL(iframe.src);
      var sessionId = u.searchParams.get('session_id');
      var participantId = u.searchParams.get('participant_id');
      if (!sessionId || !participantId) return null;
      if (participantId.indexOf('${e://') >= 0 || participantId.indexOf('${') >= 0) {
        return null;
      }
      return { session_id: sessionId, participant_id: participantId };
    } catch (e) {
      return null;
    }
  }

  /** Sync handoff when user clicks Next before the 5-min timer (async fetch often too late). */
  function handoffSync(reason) {
    if (window.__actrSaved) return;
    var params = parseIframeParams();
    if (!params) return;

    var url = getApiBase() + '/api/embed/handoff';
    try {
      var xhr = new XMLHttpRequest();
      xhr.open('POST', url, false);
      xhr.setRequestHeader('Content-Type', 'application/json');
      xhr.send(
        JSON.stringify({
          session_id: params.session_id,
          participant_id: params.participant_id,
          reason: reason || 'qualtrics_next',
        })
      );
      if (xhr.status !== 200) {
        console.warn('[ACTR] handoff HTTP', xhr.status);
        return;
      }
      var data = JSON.parse(xhr.responseText);
      saveActr({
        source: 'ACTR_CHAT',
        event: 'chat_ended',
        transcript_text: data.transcript_text,
        chat_status: data.chat_status,
        qualtrics_field_transcript: data.qualtrics_field_transcript,
        qualtrics_field_status: data.qualtrics_field_status,
        auto_advance: false,
      });
    } catch (e) {
      console.warn('[ACTR] sync handoff failed', e);
    }
  }

  function onMessage(event) {
    saveActr(event.data);
  }

  function bindListener() {
    window.addEventListener('message', onMessage, false);
  }

  function hookQualtricsNavigation() {
    var next = document.getElementById('NextButton');
    if (next) {
      next.addEventListener(
        'click',
        function () {
          handoffSync('qualtrics_next_click');
        },
        true
      );
    }
  }

  function init() {
    bindListener();
    hookQualtricsNavigation();
    if (window.Qualtrics && window.Qualtrics.SurveyEngine && window.Qualtrics.SurveyEngine.addOnUnload) {
      window.Qualtrics.SurveyEngine.addOnUnload(function () {
        handoffSync('qualtrics_unload');
      });
    }
  }

  if (window.Qualtrics && window.Qualtrics.SurveyEngine && window.Qualtrics.SurveyEngine.addOnload) {
    window.Qualtrics.SurveyEngine.addOnload(init);
  } else {
    init();
  }
})();
