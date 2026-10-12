from evennia.scripts.scripts import DefaultScript


class QuietReview(DefaultScript):
    """Configure as a persistent global script; manual +build/quiet also refreshes."""

    def at_script_creation(self):
        self.key = "building_quiet_review"
        self.desc = "Flag quiet properties for staff review without reclaiming them."
        self.interval = 86400
        self.persistent = True
        self.start_delay = True

    def at_repeat(self):
        from .frontier_lifecycle import check_quiet as check_stewards
        from .lifecycle import check_quiet

        check_quiet()
        check_stewards()
