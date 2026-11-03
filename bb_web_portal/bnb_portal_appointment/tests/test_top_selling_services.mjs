import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {test} from 'node:test';

const source = readFileSync(new URL('../static/src/js/base.js', import.meta.url), 'utf8');
function fixture() {
    const cards = Array.from({length: 12}, (_, i) => ({
        dataset: {serviceId: String(i + 1), categoryId: i < 6 ? 'a' : 'b',
            parentId: i < 6 ? 'p1' : 'p2', soldQuantity: String(i + 1)}, style: {}}));
    cards.push({dataset: {serviceId: '13', categoryId: 'c', parentId: 'p3', soldQuantity: '0'}, style: {}});
    const tabs = ['all', 'a', 'b', 'c'].map((id, i) => ({
        dataset: {categoryId: id, parentId: ['all', 'p1', 'p2', 'p3'][i]}, style: {},
        classList: {add() {}, remove() {}}, click() { handler.filterByChild(this); }}));
    const dropdown = {value: 'all'}, empty = {style: {}};
    const ordered = [...cards];
    const list = {appendChild(card) { ordered.splice(ordered.indexOf(card), 1); ordered.push(card); }};
    const Utils = {
        $(selector) { return {'#parentCategoryDropdown': dropdown,
            '.service-items-list': list, '.top-selling-empty': empty}[selector]; },
        $$(selector) { return selector === '.service-tab' ? tabs : cards; }
    };
    const context = vm.createContext({Utils, BaseHandler: class {}});
    vm.runInContext(source.slice(source.indexOf('class ServiceHandler extends'),
        source.indexOf('class DateTimeHandler extends')) + '\nglobalThis.Handler = ServiceHandler;', context);
    const handler = Object.create(context.Handler.prototype);
    handler.serviceCatalog = cards;
    return {handler, tabs, cards, dropdown, empty,
        visible: () => ordered.filter(c => c.style.display !== 'none').map(c => c.dataset.serviceId)};
}

test('Top Selling ranks actual sold units and limits to ten, excluding unsold services', () => {
    const f = fixture(); f.handler.filterByChild(f.tabs[0]);
    assert.deepEqual(f.visible(), ['12','11','10','9','8','7','6','5','4','3']);
});
test('Changing parent refreshes top sellers within that category only', () => {
    const f = fixture();
    f.dropdown.value = 'p1'; f.handler.filterByParent(f.dropdown);
    assert.deepEqual(f.visible(), ['6','5','4','3','2','1']);
    f.dropdown.value = 'p2'; f.handler.filterByParent(f.dropdown);
    assert.deepEqual(f.visible(), ['12','11','10','9','8','7']);
    assert.equal(f.tabs[1].style.display, 'none');
});
test('Regular category restores catalog order and preserves selected card objects', () => {
    const f = fixture(); f.cards[0].selected = true;
    f.handler.filterByChild(f.tabs[0]);
    f.handler.filterByChild(f.tabs[1]);
    assert.deepEqual(f.visible(), ['1','2','3','4','5','6']);
    assert.equal(f.cards[0].selected, true);
});
test('Unsold category has an honest empty message and services remain bookable', () => {
    const f = fixture(); f.dropdown.value = 'p3'; f.handler.filterByParent(f.dropdown);
    assert.deepEqual(f.visible(), []); assert.equal(f.empty.style.display, '');
    f.handler.filterByChild(f.tabs[3]);
    assert.deepEqual(f.visible(), ['13']); assert.equal(f.empty.style.display, 'none');
});
test('Ties are deterministic and returning to All Categories restores all-branch ranking', () => {
    const f = fixture(); f.cards[0].dataset.soldQuantity = '12';
    f.dropdown.value = 'p1'; f.handler.filterByParent(f.dropdown);
    f.dropdown.value = 'all'; f.handler.filterByParent(f.dropdown);
    assert.deepEqual(f.visible().slice(0, 2), ['1', '12']);
});
