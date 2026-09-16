import { useCallback, useEffect, useRef, useState } from "react";
import { postAttendanceEvent } from "../../api/attendanceApi";
import { apiFetch } from "../../api/client";
import brand from "../../branding/brand.json";

const scriptPromises = new Map();

function loadJitsiScript(scriptUrl) {
  if (scriptPromises.has(scriptUrl)) return scriptPromises.get(scriptUrl);

  const promise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    const fail = () => {
      window.clearTimeout(timeout);
      script.remove();
      scriptPromises.delete(scriptUrl);
      reject(new Error("The video service could not be loaded. Check your connection and reload the page."));
    };
    const timeout = window.setTimeout(fail, 20000);
    script.addEventListener("load", () => {
      window.clearTimeout(timeout);
      if (window.JitsiMeetExternalAPI) resolve();
      else fail();
    }, { once: true });
    script.addEventListener("error", fail, { once: true });
    script.src = scriptUrl;
    script.async = true;
    document.body.appendChild(script);
  });

  scriptPromises.set(scriptUrl, promise);
  return promise;
}

function describeJitsiError(error) {
  const parts = [error?.type, error?.name, error?.message].filter(Boolean);
  if (error?.details) {
    try {
      parts.push(typeof error.details === "string" ? error.details : JSON.stringify(error.details));
    } catch {
      parts.push("Additional diagnostic details were unavailable.");
    }
  }
  return parts.join(" · ") || "The video service did not provide a disconnect reason.";
}

/**
 * Jitsi IFrame classroom with authenticated attendance, durable faculty
 * controls, fullscreen enforcement, and visible connection diagnostics.
 */
export default function Classroom({ roomId, courseId, studentId, studentName, sessionId, isFaculty }) {
  const containerRef = useRef(null);
  const wrapperRef = useRef(null);
  const apiRef = useRef(null);
  const joinedRef = useRef(false);
  const leaveSentRef = useRef(false);
  const intentionalExitRef = useRef(false);
  const lastErrorRef = useRef("");
  const fullscreenRequiredRef = useRef(true);
  const sessionEndedRef = useRef(false);
  const joinTimeoutRef = useRef(null);
  const recordingRequestedRef = useRef(false);
  const recordingModeRef = useRef(null);

  const [fullscreenRequired, setFullscreenRequired] = useState(true);
  const [isCurrentlyFullscreen, setIsCurrentlyFullscreen] = useState(false);
  const [togglingFullscreen, setTogglingFullscreen] = useState(false);
  const [endingClass, setEndingClass] = useState(false);
  const [callStatus, setCallStatus] = useState("loading");
  const [diagnostic, setDiagnostic] = useState("");
  const [recordingStatus, setRecordingStatus] = useState("unavailable");

  const sendAttendance = useCallback(
    (eventType, keepalive = false) => {
      if (isFaculty) return Promise.resolve(null);
      if (eventType === "left") {
        if (!joinedRef.current || leaveSentRef.current) return Promise.resolve(null);
        leaveSentRef.current = true;
      }
      return postAttendanceEvent(
        {
          room_id: roomId,
          course_id: courseId,
          student_id: studentId,
          event_type: eventType,
          timestamp: new Date().toISOString(),
        },
        { keepalive }
      );
    },
    [roomId, courseId, studentId, isFaculty]
  );

  useEffect(() => {
    let cancelled = false;
    const abortController = new AbortController();
    joinedRef.current = false;
    leaveSentRef.current = false;
    intentionalExitRef.current = false;
    sessionEndedRef.current = false;
    lastErrorRef.current = "";
    recordingRequestedRef.current = false;
    recordingModeRef.current = null;
    setRecordingStatus("unavailable");
    setCallStatus("loading");
    setDiagnostic("");

    apiFetch(`/attendance/sessions/${sessionId}/connection`, {
      method: "POST", signal: abortController.signal,
    })
      .then(async (connection) => {
        if (cancelled) return;
        await loadJitsiScript(connection.script_url);
        if (cancelled || !containerRef.current) return;
        if (sessionEndedRef.current) {
          setCallStatus("ended");
          return;
        }

        const api = new window.JitsiMeetExternalAPI(connection.domain, {
          roomName: connection.room_name,
          ...(connection.jwt ? { jwt: connection.jwt } : {}),
          parentNode: containerRef.current,
          userInfo: { displayName: studentName },
          width: "100%",
          height: "100%",
          configOverwrite: {
            prejoinConfig: { enabled: false },
            startWithAudioMuted: !isFaculty,
            startWithVideoMuted: !isFaculty,
            buttonsWithNotifyClick: [{ key: "hangup", preventExecution: false }],
          },
          interfaceConfigOverwrite: {
            APP_NAME: brand.name,
            NATIVE_APP_NAME: brand.name,
            PROVIDER_NAME: brand.name,
            SHOW_JITSI_WATERMARK: false,
            SHOW_WATERMARK_FOR_GUESTS: false,
            SHOW_BRAND_WATERMARK: false,
            SHOW_POWERED_BY: false,
            TOOLBAR_BUTTONS: ["microphone", "camera", "desktop", "chat", "raisehand", "tileview", "hangup"],
          },
        });
        apiRef.current = api;
        if (isFaculty && connection.recording?.available) {
          recordingModeRef.current = connection.recording.mode || "file";
          setRecordingStatus("ready");
        }
        setCallStatus("connecting");
        joinTimeoutRef.current = window.setTimeout(() => {
          if (!joinedRef.current && !sessionEndedRef.current) {
            setDiagnostic(
              `The room has not connected. ${connection.domain} may be waiting for the instructor or media permission. If your join token expired, reload this page.`
            );
          }
        }, 15000);

        api.addEventListener("videoConferenceJoined", () => {
          window.clearTimeout(joinTimeoutRef.current);
          joinedRef.current = true;
          leaveSentRef.current = false;
          setCallStatus("joined");
          setDiagnostic("");
          sendAttendance("joined");
          if (!isFaculty && fullscreenRequiredRef.current) {
            wrapperRef.current?.requestFullscreen?.().catch(() => {
              // Browsers may require a direct click; the blocking overlay
              // remains visible and provides that user gesture as fallback.
            });
          }
        });

        api.addEventListener("participantRoleChanged", ({ role }) => {
          if (isFaculty && role === "moderator" && connection.recording?.auto_start
              && !recordingRequestedRef.current) {
            recordingRequestedRef.current = true;
            setRecordingStatus("starting");
            api.executeCommand("startRecording", {
              mode: connection.recording.mode || "file",
              shouldShare: true,
              extraMetadata: { ekeekrta_session_id: String(sessionId),
                               ekeekrta_course_id: String(courseId) },
            });
          }
        });

        api.addEventListener("recordingStatusChanged", ({ on, mode, error }) => {
          if (mode && mode !== recordingModeRef.current) return;
          if (error) {
            recordingRequestedRef.current = false;
            setRecordingStatus("failed");
            setDiagnostic(`Server recording failed · ${error}`);
            return;
          }
          setRecordingStatus(on ? "recording" : "stopped");
        });

        api.addEventListener("toolbarButtonClicked", ({ key }) => {
          if (key === "hangup") intentionalExitRef.current = true;
        });

        api.addEventListener("errorOccurred", (error) => {
          const reason = describeJitsiError(error);
          lastErrorRef.current = reason;
          if (error?.isFatal) setDiagnostic(reason);
        });

        api.addEventListener("cameraError", (error) => {
          lastErrorRef.current = `Camera error · ${error?.type || "unknown"} · ${error?.message || "No details"}`;
          setDiagnostic(lastErrorRef.current);
        });

        api.addEventListener("micError", (error) => {
          lastErrorRef.current = `Microphone error · ${error?.type || "unknown"} · ${error?.message || "No details"}`;
          setDiagnostic(lastErrorRef.current);
        });

        api.addEventListener("browserSupport", ({ supported }) => {
          if (!supported) {
            lastErrorRef.current = "This browser is not supported by the configured Jitsi service.";
            setDiagnostic(lastErrorRef.current);
          }
        });

        api.addEventListener("notificationTriggered", ({ title, description }) => {
          const notification = [title, description].filter(Boolean).join(" · ");
          if (notification) lastErrorRef.current = notification;
        });

        api.addEventListener("peerConnectionFailure", ({ isP2P, wasConnected }) => {
          lastErrorRef.current = `WebRTC connection failure · ${isP2P ? "peer-to-peer" : "video bridge"} · ${
            wasConnected ? "connection was interrupted" : "connection could not be established"
          }`;
        });

        api.addEventListener("participantKickedOut", ({ kicked }) => {
          if (kicked?.local) lastErrorRef.current = "You were removed from the class by a moderator.";
        });

        api.addEventListener("videoConferenceLeft", () => {
          sendAttendance("left", true);
          setCallStatus(intentionalExitRef.current ? "ended" : "disconnected");
          if (!intentionalExitRef.current) {
            setDiagnostic(lastErrorRef.current || "The call ended unexpectedly. Jitsi did not provide a disconnect reason.");
          }
        });

        api.addEventListener("readyToClose", () => setCallStatus("ended"));
      })
      .catch((error) => {
        if (!cancelled) {
          setCallStatus("error");
          setDiagnostic(error.message);
        }
      });

    return () => {
      cancelled = true;
      abortController.abort();
      window.clearTimeout(joinTimeoutRef.current);
      sendAttendance("left", true);
      apiRef.current?.dispose();
      apiRef.current = null;
    };
  }, [roomId, sessionId, studentName, sendAttendance, isFaculty]);

  useEffect(() => {
    const handleFullscreenChange = () => {
      const fullscreenElement = document.fullscreenElement;
      setIsCurrentlyFullscreen(Boolean(fullscreenElement && (
        fullscreenElement === wrapperRef.current || wrapperRef.current?.contains(fullscreenElement)
      )));
    };
    handleFullscreenChange();
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", handleFullscreenChange);
  }, []);

  useEffect(() => {
    if (!sessionId) return undefined;

    const checkSession = () =>
      apiFetch(`/attendance/sessions/detail/${sessionId}`)
        .then((session) => {
          fullscreenRequiredRef.current = session.fullscreen_required;
          setFullscreenRequired(session.fullscreen_required);
          if (session.ended_at && !intentionalExitRef.current) {
            sessionEndedRef.current = true;
            intentionalExitRef.current = true;
            setCallStatus("ended");
            setDiagnostic("The instructor ended this class for everyone.");
            apiRef.current?.executeCommand("hangup");
          }
        })
        .catch((error) => {
          lastErrorRef.current = `Session status check failed · ${error.message}`;
        });

    checkSession();
    const interval = setInterval(checkSession, 3000);
    return () => clearInterval(interval);
  }, [sessionId]);

  const enterFullscreen = () => {
    if (!wrapperRef.current?.requestFullscreen || !document.fullscreenEnabled) {
      setDiagnostic("Fullscreen is unavailable in this browser window. Open the LMS in a supported standalone browser and try again.");
      return;
    }
    wrapperRef.current?.requestFullscreen?.().catch((error) => {
      setDiagnostic(`Fullscreen request failed · ${error.message}`);
    });
  };

  const toggleFullscreenRequirement = async () => {
    if (!sessionId) return;
    setTogglingFullscreen(true);
    try {
      const updated = await apiFetch(`/attendance/sessions/${sessionId}/fullscreen`, {
        method: "PATCH",
        body: JSON.stringify({ fullscreen_required: !fullscreenRequired }),
      });
      fullscreenRequiredRef.current = updated.fullscreen_required;
      setFullscreenRequired(updated.fullscreen_required);
    } catch (error) {
      setDiagnostic(`Could not update fullscreen policy · ${error.message}`);
    } finally {
      setTogglingFullscreen(false);
    }
  };

  const endClass = async () => {
    if (!sessionId || !window.confirm("End this class for every participant?")) return;
    setEndingClass(true);
    try {
      if (recordingModeRef.current && recordingRequestedRef.current) {
        setRecordingStatus("stopping");
        apiRef.current?.executeCommand("stopRecording", recordingModeRef.current, false);
        await new Promise(resolve => window.setTimeout(resolve, 1200));
      }
      await apiFetch(`/attendance/sessions/${sessionId}/end`, { method: "PATCH" });
      sessionEndedRef.current = true;
      intentionalExitRef.current = true;
      setCallStatus("ended");
      setDiagnostic("You ended the class for everyone.");
      apiRef.current?.executeCommand("endConference");
      window.setTimeout(() => apiRef.current?.executeCommand("hangup"), 750);
      setEndingClass(false);
    } catch (error) {
      setDiagnostic(`Could not end the class · ${error.message}`);
      setEndingClass(false);
    }
  };

  const showBlockingOverlay =
    !isFaculty && fullscreenRequired && !isCurrentlyFullscreen && callStatus === "joined";

  return (
    <div ref={wrapperRef} className="classroom-shell">
      <div ref={containerRef} className="classroom-frame" />

      <div className="classroom-status" aria-live="polite">
        {callStatus === "loading" && "Loading video…"}
        {callStatus === "connecting" && "Connecting…"}
        {callStatus === "joined" && "Live"}
        {callStatus === "ended" && "Class ended"}
        {callStatus === "disconnected" && "Disconnected"}
        {callStatus === "error" && "Video unavailable"}
      </div>

      {isFaculty && sessionId && (
        <div className="classroom-controls">
          {recordingStatus !== "unavailable" && <span className="classroom-recording-status" role="status">Recording: {recordingStatus}</span>}
          <button onClick={toggleFullscreenRequirement} disabled={togglingFullscreen || endingClass} className="classroom-control">
            {fullscreenRequired ? "Fullscreen required" : "Normal screen allowed"}
          </button>
          <button onClick={endClass} disabled={endingClass || callStatus === "ended"} className="classroom-control classroom-end">
            {callStatus === "ended" ? "Class ended" : endingClass ? "Ending class…" : "End class for everyone"}
          </button>
        </div>
      )}

      {diagnostic && (
        <div className="classroom-diagnostic" role="status">
          <strong>{callStatus === "disconnected" || callStatus === "error" ? "Call diagnostic" : "Class status"}</strong>
          <span>{diagnostic}</span>
          <button onClick={() => setDiagnostic("")} aria-label="Dismiss message">×</button>
        </div>
      )}

      {showBlockingOverlay && (
        <div className="fullscreen-overlay">
          <p className="fullscreen-title">Fullscreen is required for this class</p>
          <p className="fullscreen-copy">Your instructor has not released normal-screen mode yet. Re-enter fullscreen to continue.</p>
          {diagnostic && <p className="fullscreen-copy" role="status">{diagnostic}</p>}
          <button onClick={enterFullscreen} className="btn btn-primary">Enter fullscreen</button>
        </div>
      )}
    </div>
  );
}
