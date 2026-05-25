/**
 * Qualtrics SURVEY PAGE script (not inside the iframe).
 * Paste into: Survey Flow → Add JavaScript, OR the HTML question that wraps your chat iframe.
 *
 * Listens for messages from ACTR embed (/embed.html) and:
 * 1. Saves chat transcript + status into Qualtrics Embedded Data
 * 2. Optionally auto-advances to the next survey question
 */
(function () {
  function handleActrMessage(event) {
    var data = event.data;
    if (!data || data.source !== 'ACTR_CHAT' || data.event !== 'chat_ended') {
      return;
    }

    var transcriptField = data.qualtrics_field_transcript || 'chat_transcript';
    var statusField = data.qualtrics_field_status || 'chat_status';

    if (typeof Qualtrics !== 'undefined' && Qualtrics.SurveyEngine) {
      if (data.transcript_text) {
        Qualtrics.SurveyEngine.setEmbeddedData(transcriptField, data.transcript_text);
      }
      Qualtrics.SurveyEngine.setEmbeddedData(statusField, data.reason || 'completed');

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
