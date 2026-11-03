from odoo import models


class IrRule(models.Model):
    _inherit = "ir.rule"

    def _register_hook(self):
        """Keep critical multi-company domains aligned for cross-company branches.

        Odoo core marks some XMLIDs as noupdate, so XML overrides may not be
        applied on upgrades. Enforce domains at registry load time.
        """
        res = super()._register_hook()
        self._sync_bnb_multi_company_rules()
        return res

    def _sync_bnb_multi_company_rules(self):
        # Keep core Odoo 19 HR/base rule domains unchanged.
        updates = {}
        for xmlid, domain in updates.items():
            rule = self.env.ref(xmlid, raise_if_not_found=False)
            if rule and rule.domain_force != domain:
                rule.sudo().write({"domain_force": domain})
