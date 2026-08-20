/**
 * Filtre live Alpine pour les tableaux listes mag.
 * Usage: x-data="magTableFilter()" sur .mag-table-shell
 */
function magTableFilter() {
    return {
        query: '',
        totalCount: 0,
        visibleCount: 0,
        _rows: [],
        _emptyEl: null,
        _timer: null,

        init() {
            var root = this.$el;
            this._rows = Array.prototype.slice.call(
                root.querySelectorAll('tbody tr')
            ).filter(function (tr) {
                return !tr.classList.contains('mag-table-skip-filter');
            });
            this._emptyEl = root.querySelector('[data-mag-table-empty]');
            this.totalCount = this._rows.length;
            this.visibleCount = this._rows.length;
            this._rows.forEach(function (tr) {
                if (!tr.getAttribute('data-search')) {
                    tr.setAttribute(
                        'data-search',
                        (tr.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase()
                    );
                }
            });
        },

        filter() {
            var self = this;
            if (this._timer) window.clearTimeout(this._timer);
            this._timer = window.setTimeout(function () {
                self._applyFilter();
            }, 120);
        },

        _applyFilter() {
            var q = String(this.query || '').trim().toLowerCase();
            var visible = 0;
            this._rows.forEach(function (tr) {
                var hay = tr.getAttribute('data-search') || '';
                var match = !q || hay.indexOf(q) !== -1;
                tr.classList.toggle('is-filtered-out', !match);
                if (match) visible += 1;
            });
            this.visibleCount = visible;
            if (this._emptyEl) {
                this._emptyEl.classList.toggle('is-visible', visible === 0 && this.totalCount > 0);
            }
        },

        clear() {
            this.query = '';
            this._applyFilter();
        }
    };
}

window.magTableFilter = magTableFilter;
