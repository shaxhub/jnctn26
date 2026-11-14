from dataclasses import replace

from gateway import demo_catalog, offers, search, seed_demo, store
from test_portals import gateway


def test_seed_populates_both_workspaces_without_overwriting_existing_data(gateway, monkeypatch, tmp_path):
    catalog = replace(demo_catalog.settings, catalog_db_path=tmp_path / 'catalog.db')
    monkeypatch.setenv('OFFLINE_DEMO', '1')
    monkeypatch.setattr(demo_catalog, 'settings', catalog)
    monkeypatch.setattr(search, 'settings', catalog)
    monkeypatch.setattr(seed_demo, 'settings', replace(catalog, db_path=store.settings.db_path))
    monkeypatch.setattr(seed_demo.service, 'get_offers', offers.get_offers)
    search._catalog_path.cache_clear()
    demo_catalog.build()
    store.execute("INSERT INTO ticket_names VALUES ('existing-draft','Do not remove')")
    try:
        result = seed_demo.seed(backup=False)
        assert result['created'] == 17
        assert store.fetchone("SELECT name FROM ticket_names WHERE quote_id='existing-draft'")['name'] == 'Do not remove'
        for buyer in ('hotel', 'hospital'):
            statuses = dict((row['status'], row['n']) for row in store.fetchall(
                'SELECT status,count(*) AS n FROM orders WHERE buyer_id=? GROUP BY status', (buyer,)))
            assert statuses['confirmed'] == 6 and statuses['pending_approval'] == 1
            assert store.fetchone("SELECT count(*) AS n FROM quotes WHERE buyer_id=? AND status='open'", (buyer,))['n'] == 1
        assert store.fetchone("SELECT count(*) AS n FROM orders WHERE status='rejected'")['n'] == 1
        before = store.verify_chain()
        repeated = seed_demo.seed(backup=False)
        assert repeated['created'] == 0 and repeated['skipped'] == 17
        assert store.verify_chain() == before and before['ok']
    finally:
        search._catalog_path.cache_clear()
