import { useMemo, useState } from "react";

function NotificationPanel({
  risk,
  weather,
  routes,
  incidents,
}) {
  const [readNotifications, setReadNotifications] =
    useState(new Set());

  const notifications = useMemo(() => {
    const items = [];

    // High-risk route alert
    const routeRisk = routes?.normal?.risk_score ?? 0;

    if (routeRisk >= 70) {
      items.push({
        id: "high-risk-route",
        type: "HIGH_RISK",
        title: "High-Risk Road Alert",
        message:
          "The primary route has a high predicted risk.",
        severity: "HIGH",
      });
    }

    // AI environmental risk alert
    const riskLevel = risk?.prediction?.level;

    if (
      typeof riskLevel === "string" &&
      riskLevel.toUpperCase() === "HIGH"
    ) {
      items.push({
        id: "environmental-risk",
        type: "ENVIRONMENTAL",
        title: "Environmental Risk Alert",
        message:
          "The AI system has detected high environmental risk.",
        severity: "HIGH",
      });
    }

    // Road incident alerts
    (Array.isArray(incidents) ? incidents : []).forEach(
      (incident) => {
        const incidentType = String(
          incident.type ?? "INCIDENT"
        ).toUpperCase();

        const isBlockedRoad = [
          "ROAD_BLOCK",
          "BLOCKED_ROAD",
          "ROAD_BLOCKED",
        ].includes(incidentType);

        items.push({
          id: `incident-${incident.id}`,
          type: isBlockedRoad
            ? "BLOCKED_ROAD"
            : "INCIDENT",
          title: isBlockedRoad
            ? "Blocked Road Alert"
            : "Incident Report",
          message:
            incident.description ||
            `${incidentType.replaceAll("_", " ")} reported.`,
          severity: incident.severity ?? "UNKNOWN",
        });
      }
    );

    return items;
  }, [risk, weather, routes, incidents]);

  const unreadCount = notifications.filter(
    (notification) =>
      !readNotifications.has(notification.id)
  ).length;

  function markAsRead(id) {
    setReadNotifications((previous) => {
      const updated = new Set(previous);
      updated.add(id);
      return updated;
    });
  }

  function markAllAsRead() {
    setReadNotifications(
      new Set(notifications.map((item) => item.id))
    );
  }

  return (
    <div className="panel">
      <div className="panel-title">
        Notifications ({unreadCount} unread)
      </div>

      {notifications.length > 0 && (
        <button
          type="button"
          onClick={markAllAsRead}
        >
          Mark All as Read
        </button>
      )}

      {notifications.length === 0 ? (
        <p className="empty">
          No current alerts.
        </p>
      ) : (
        notifications.map((notification) => {
          const isRead = readNotifications.has(
            notification.id
          );

          return (
            <div
              key={notification.id}
              className={`notification-item ${
                isRead ? "read" : "unread"
              }`}
            >
              <div>
                <strong>{notification.title}</strong>

                <p>{notification.message}</p>

                <small>
                  Severity: {notification.severity}
                </small>
              </div>

              {!isRead && (
                <button
                  type="button"
                  onClick={() =>
                    markAsRead(notification.id)
                  }
                >
                  Mark Read
                </button>
              )}
            </div>
          );
        })
      )}
    </div>
  );
}

export default NotificationPanel;