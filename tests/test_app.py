from collections import deque
from concurrent.futures import Future
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from profile_manager.app import ProfileManagerApp
from profile_manager.models import RuntimeState


class ProfileManagerAppTests(TestCase):
    def test_profile_mutation_completes_on_tk_callback(self):
        for action in ("edit", "delete"):
            for fails in (False, True):
                with self.subTest(action=action, fails=fails):
                    self._assert_profile_mutation(action, fails)

    def _assert_profile_mutation(self, action, fails):
        callbacks = deque()
        future = Future()
        profile = SimpleNamespace(id="profile", name="Original", proxy=None, settings={})
        updated = SimpleNamespace(id=profile.id, name="Updated")
        app = ProfileManagerApp.__new__(ProfileManagerApp)
        app.root = SimpleNamespace(after=lambda delay, callback: callbacks.append(callback), wait_window=Mock())
        app.selected_profile = lambda: profile
        app._state = lambda _: RuntimeState.STOPPED
        app.worker = SimpleNamespace(submit=Mock(return_value=future))
        app.service = SimpleNamespace(mutate_profile=Mock())
        app.store = Mock()
        app.states = {profile.id: RuntimeState.STOPPED}
        app.refresh_profiles = Mock()
        app.status_var = Mock()
        app.toast = Mock()
        app.shutting_down = False
        showerror = Mock()

        def pending_result():
            self.fail("Read a pending future")

        result = Mock(wraps=future.result, side_effect=pending_result)
        future.result = result
        with (
            patch("profile_manager.app.ProfileDialog", return_value=SimpleNamespace(result={"name": updated.name})),
            patch("profile_manager.app.messagebox.askyesno", return_value=True),
            patch("profile_manager.app.messagebox.showerror", showerror),
        ):
            getattr(app, f"{action}_profile")()
            callbacks.popleft()()
            result.assert_not_called()
            app.refresh_profiles.assert_not_called()
            result.side_effect = None
            if fails:
                future.set_exception(ValueError("mutation failed"))
            else:
                future.set_result(updated if action == "edit" else None)
            app.refresh_profiles.assert_not_called()
            showerror.assert_not_called()
            callbacks.popleft()()

        if fails:
            self.assertEqual(showerror.call_args.args[1], "mutation failed")
            app.refresh_profiles.assert_not_called()
            app.toast.show.assert_not_called()
            self.assertIn(profile.id, app.states)
        else:
            showerror.assert_not_called()
            if action == "edit":
                app.refresh_profiles.assert_called_once_with(updated.id)
            else:
                app.refresh_profiles.assert_called_once_with()
                self.assertNotIn(profile.id, app.states)
            app.toast.show.assert_called_once()
