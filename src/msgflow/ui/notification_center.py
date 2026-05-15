import uuid

import objc
from AppKit import NSObject
from UserNotifications import (
    UNAuthorizationOptionAlert,
    UNAuthorizationOptionSound,
    UNAuthorizationStatusNotDetermined,
    UNMutableNotificationContent,
    UNNotificationPresentationOptionBanner,
    UNNotificationPresentationOptionList,
    UNNotificationPresentationOptionSound,
    UNNotificationRequest,
    UNNotificationSound,
    UNUserNotificationCenter,
)


class NotificationPresenter(NSObject):
    def init(self):  # type: ignore[override]
        self = objc.super(NotificationPresenter, self).init()
        if self is None:
            return None
        self.center = UNUserNotificationCenter.currentNotificationCenter()
        self.center.setDelegate_(self)
        self.authorization_status = UNAuthorizationStatusNotDetermined
        return self

    @objc.python_method
    def request_authorization(self) -> None:
        options = UNAuthorizationOptionAlert | UNAuthorizationOptionSound

        def _settings_handler(settings) -> None:
            self.authorization_status = int(settings.authorizationStatus())

        def _completion(_granted: bool, _error) -> None:
            self.center.getNotificationSettingsWithCompletionHandler_(_settings_handler)

        self.center.getNotificationSettingsWithCompletionHandler_(_settings_handler)
        self.center.requestAuthorizationWithOptions_completionHandler_(options, _completion)

    def show_notification(self, title: str, body: str) -> None:
        content = UNMutableNotificationContent.alloc().init()
        content.setTitle_(title)
        content.setBody_(body)
        content.setSound_(UNNotificationSound.defaultSound())
        request = UNNotificationRequest.requestWithIdentifier_content_trigger_(
            str(uuid.uuid4()),
            content,
            None,
        )
        self.center.addNotificationRequest_withCompletionHandler_(request, None)

    def userNotificationCenter_willPresentNotification_withCompletionHandler_(
        self,
        _center,
        _notification,
        completion_handler,
    ) -> None:
        options = (
            UNNotificationPresentationOptionBanner
            | UNNotificationPresentationOptionList
            | UNNotificationPresentationOptionSound
        )
        completion_handler(options)
