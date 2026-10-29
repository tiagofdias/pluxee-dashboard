import unittest
from unittest.mock import patch

import history_store
import monitor
from pluxee_api import compute_effective_balance


class TransactionRegressionTests(unittest.TestCase):
    def test_settlement_updates_history_without_another_alert(self):
        pending = dict(date='15/06/2026', description='LOJA EXEMPLO', amount=-5.5,
                       balance=None, effective_date=None, raw_description='LOJA EXEMPLO')
        settled = dict(pending, balance=108.5, effective_date='16/06/2026',
                       raw_description='Compra LOJA EXEMPLO,CIDADE,PRT')
        balance = {'lunch_pass': 108.5}
        previous = dict(transactions=[pending], fingerprints=['legacy-hash'], balance=balance)
        result = dict(balance=balance, transactions=[settled])
        with patch.object(monitor, 'fetch_all', return_value=result), \
             patch.object(monitor, 'load_state', return_value=previous), \
             patch.object(monitor, '_load_outage_state', return_value=None), \
             patch.object(monitor, 'save_state') as save, \
             patch.object(monitor, 'notify_transaction') as notify, \
             patch.object(monitor, 'send_notification') as send:
            count, actual = monitor.check_for_new_transactions(
                dict(api_claim='test', card_id='test', benefit_id='test'))
        self.assertEqual(count, 0)
        self.assertEqual(actual, balance)
        notify.assert_not_called()
        send.assert_not_called()
        save.assert_called_once_with(balance, [settled])
        self.assertEqual(history_store.merge_transactions([pending], [settled]), [settled])

    def test_card_balance_overrides_inconsistent_movement_snapshots(self):
        self.assertEqual(compute_effective_balance(108.5, [
            dict(amount=102.1, balance=130.6),
            dict(amount=-5.5, balance=108.5),
            dict(amount=-16.6, balance=114.0),
        ]), 108.5)
        self.assertEqual(compute_effective_balance(6.54, [
            dict(amount=-5.5, balance=None),
            dict(amount=-16.6, balance=28.64),
        ]), 6.54)


if __name__ == '__main__':
    unittest.main()
