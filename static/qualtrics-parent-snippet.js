/**
 * Qualtrics SURVEY PAGE script (not inside the iframe).
 * Paste into: Survey Flow → Add JavaScript, OR the HTML question that wraps your chat iframe.
 *
 * Listens for messages from ACTR embed (/embed.html) and:
 * 1. Saves chat transcript into Qualtrics Embedded Data
 * 2. Auto-advances to the next survey question when integration is enabled
 */
(function () {
  function handleActrMessage(event) {
    var data = event.data;
    if (!data || data.source !== 'ACTR_CHAT' || data.event !== 'chat_ended') {
      return;
    }

    var transcriptField = data.qualtrics_field_transcript || 'transcript';

    if (typeof Qualtrics !== 'undefined' && Qualtrics.SurveyEngine) {
      if (data.transcript_text) {
        Qualtrics.SurveyEngine.setEmbeddedData(transcriptField, data.transcript_text);
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
