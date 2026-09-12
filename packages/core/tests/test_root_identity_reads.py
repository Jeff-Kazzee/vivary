"""Non-enrolling availability uses live custody without durable metadata writes."""
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vivary_core.physical_observe import ObservationFailure
from vivary_core.root_identity_lifecycle import RootIdentityLifecycle
from test_physical_observe import tree_state


@unittest.skipUnless(sys.platform == "linux", "Linux physical custody proof")
class IdentityReadTests(unittest.TestCase):
    def setUp(self):
        base = os.environ.get("VIVARY_ROOT_IDENTITY_PROOF_ROOT")
        if base is not None and not Path(base).is_absolute():
            self.fail("VIVARY_ROOT_IDENTITY_PROOF_ROOT must be absolute when set")
        self.temporary = tempfile.TemporaryDirectory(dir=base, prefix="read-")
        self.base = Path(self.temporary.name)
        self.scope = self.base / "projects"
        self.scope.mkdir()
        self.root = self.scope / "root"
        self.root.mkdir()
        (self.root / "note.txt").write_text("unchanged project\n")
        self.state_dir = self.base / "private"
        self.state_dir.mkdir()
        self.state = self.state_dir / "roots.json"
        self.owners = []

    def tearDown(self):
        for owner in self.owners:
            owner.close()
        self.state_dir.chmod(0o700)
        self.temporary.cleanup()

    def owner(self, **changes):
        args = dict(device_id="device-read", scope=self.scope, locations={"root": self.root}, state_path=self.state)
        args.update(changes)
        result = RootIdentityLifecycle(**args)
        self.owners.append(result)
        return result

    def test_unregistered_read_never_allocates_or_writes_metadata(self):
        owner = self.owner()
        metadata = tree_state(self.state_dir)
        project = tree_state(self.scope)
        with patch("vivary_core.root_identity_lifecycle.uuid4", side_effect=AssertionError("read allocated identity")):
            first = owner.inspect_location("root")
            second = owner.inspect_location("root")
        self.assertIsNone(first.root_id)
        self.assertIsNone(second.root_id)
        self.assertEqual(first.location_ref, "root")
        self.assertEqual(first.layout, "none")
        self.assertEqual(first.content_revision, second.content_revision)
        self.assertFalse(first.mutation_authorized)
        self.assertFalse(self.state.exists())
        self.assertEqual(tree_state(self.state_dir), metadata)
        self.assertEqual(tree_state(self.scope), project)

    def test_enrolled_read_uses_existing_id_without_rewriting_state(self):
        owner = self.owner()
        enrolled = owner.enroll("root")
        before = tree_state(self.state_dir)
        with patch.object(owner, "_save", side_effect=AssertionError("read persisted state")):
            current = owner.inspect_location("root")
        self.assertEqual(current.root_id, enrolled.root_id)
        self.assertEqual(tree_state(self.state_dir), before)

    def test_alias_read_does_not_add_a_persisted_locator(self):
        owner = self.owner(locations={"root": self.root, "alias": self.root})
        enrolled = owner.enroll("root")
        before = tree_state(self.state_dir)
        read = owner.inspect_location("alias")
        self.assertEqual(read.root_id, enrolled.root_id)
        self.assertEqual(tree_state(self.state_dir), before)
        self.assertNotIn("alias", self.state.read_text())

    def test_restart_and_replacement_refuse_without_reconciling(self):
        owner = self.owner()
        owner.enroll("root")
        before = tree_state(self.state_dir)
        self.root.rename(self.scope / "moved")
        self.root.mkdir()
        self.assertIsInstance(owner.inspect_location("root"), ObservationFailure)
        self.assertEqual(tree_state(self.state_dir), before)
        owner.close()
        restarted = self.owner()
        self.assertIsInstance(restarted.inspect_location("root"), ObservationFailure)
        self.assertEqual(tree_state(self.state_dir), before)

    def test_missing_grant_and_epoch_loss_never_create_state(self):
        epoch = ["first"]
        owner = self.owner(epoch_reader=lambda: epoch[0])
        before = tree_state(self.state_dir)
        self.assertIsInstance(owner.inspect_location("missing"), ObservationFailure)
        epoch[0] = "changed"
        self.assertIsInstance(owner.inspect_location("root"), ObservationFailure)
        self.assertEqual(tree_state(self.state_dir), before)

    def test_read_works_with_metadata_directory_not_writable(self):
        owner = self.owner()
        before = tree_state(self.state_dir)
        self.state_dir.chmod(0o500)
        try:
            self.assertIsNone(owner.inspect_location("root").root_id)
            self.assertFalse(self.state.exists())
        finally:
            self.state_dir.chmod(0o700)
        self.assertEqual(tree_state(self.state_dir), before)


if __name__ == "__main__":
    unittest.main()
