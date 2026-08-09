// background.js — Handles background extension lifecycle and auto-starting the FastAPI bridge
// via Native Messaging when requested by the popup.

chrome.runtime.onInstalled.addListener(() => {
  console.log('Tab Researcher Extension Installed.');
});

// Listener for messages from the popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'ensure_bridge') {
    console.log('Popup requested bridge check. Attempting Native Messaging launch...');
    
    try {
      // Connect to the local native messaging host registered on the user's OS
      const port = chrome.runtime.connectNative('com.tabresearcher.bridge_launcher');
      
      port.postMessage({ command: 'start_bridge' });
      
      port.onMessage.addListener((msg) => {
        console.log('Received response from native launcher:', msg);
      });
      
      port.onDisconnect.addListener(() => {
        if (chrome.runtime.lastError) {
          console.warn('Native messaging host disconnected:', chrome.runtime.lastError.message);
        } else {
          console.log('Native messaging host disconnected cleanly.');
        }
      });
      
      sendResponse({ status: 'spawn_attempted' });
    } catch (err) {
      console.warn('Failed to start bridge via Native Messaging:', err);
      sendResponse({ status: 'failed', error: err.message });
    }
    return true; // Keep channel open for async sendResponse
  }
});
