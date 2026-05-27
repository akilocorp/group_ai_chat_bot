/**
 * Qualtrics SURVEY PAGE script (not inside the iframe).
 * Paste into: Survey Flow → Add JavaScript, OR the HTML question that wraps your chat iframe.
 *
 * Listens for messages from ACTR embed (/embed.html) and:
 * 1. Saves chat transcript into Qualtrics Embedded Data
 * 2. Saves chat_status (completed_full | left_early | no_messages | never_joined)
 * 3. Auto-advances only when chat_status is completed_full (full group duration)
 */
(function () {
  function handleActrMessage(event) {
    var data = event.data;
    if (!data || data.source !== 'ACTR_CHAT' || data.event !== 'chat_ended') {
      return;
    }

    var transcriptField = data.qualtrics_field_transcript || 'transcript';
    var statusField = data.qualtrics_field_status || 'chat_status';

    if (typeof Qualtrics !== 'undefined' && Qualtrics.SurveyEngine) {
      if (data.transcript_text) {
        Qualtrics.SurveyEngine.setEmbeddedData(transcriptField, data.transcript_text);
      }
      if (data.chat_status) {
        Qualtrics.SurveyEngine.setEmbeddedData(statusField, data.chat_status);
      }

      if (data.auto_advance) {
        var se = Qualtrics.SurveyEngine;
        if (se.clickNextButton) {
          se.clickNextButton();
        }
      }
    }
  }

  window.addEventListener('message', handleActrMessage, false);
})();
