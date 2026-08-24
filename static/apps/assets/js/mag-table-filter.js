/**
 * Filtre live Alpine pour les tableaux listes mag.
 * Usage: x-data="magTableFilter()" sur .mag-table-shell
 * Pagination optionnelle : magTableFilter(10)
 */
function magTableFilter(pageSize) {
    var size = parseInt(pageSize, 10);
    if (isNaN(size) || size < 0) size = 0;

    return {
        query: '',
        totalCount: 0,
        visibleCount: 0,
        page: 1,
        pageSize: size,
        pageCount: 1,
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
            this._applyFilter();
        },

        filter() {
            var self = this;
            this.page = 1;
            if (this._timer) window.clearTimeout(this._timer);
            this._timer = window.setTimeout(function () {
                self._applyFilter();
            }, 120);
        },

        _matchedRows() {
            var q = String(this.query || '').trim().toLowerCase();
            return this._rows.filter(function (tr) {
                var hay = tr.getAttribute('data-search') || '';
                return !q || hay.indexOf(q) !== -1;
            });
        },

        _applyFilter() {
            var matched = this._matchedRows();
            this.visibleCount = matched.length;
            if (this._emptyEl) {
                this._emptyEl.classList.toggle('is-visible', matched.length === 0 && this.totalCount > 0);
            }

            var start = 0;
            var end = matched.length;
            if (this.pageSize > 0) {
                this.pageCount = Math.max(1, Math.ceil(matched.length / this.pageSize) || 1);
                if (this.page > this.pageCount) this.page = this.pageCount;
                if (this.page < 1) this.page = 1;
                start = (this.page - 1) * this.pageSize;
                end = start + this.pageSize;
            } else {
                this.pageCount = 1;
                this.page = 1;
            }

            var shownStart = start;
            var shownEnd = end;
            this._rows.forEach(function (tr) {
                var onPage = matched.indexOf(tr);
                var hide = onPage === -1 || onPage < shownStart || onPage >= shownEnd;
                tr.classList.toggle('is-filtered-out', hide);
            });
        },

        prevPage() {
            if (this.page <= 1) return;
            this.page -= 1;
            this._applyFilter();
        },

        nextPage() {
            if (this.page >= this.pageCount) return;
            this.page += 1;
            this._applyFilter();
        },

        clear() {
            this.query = '';
            this.page = 1;
            this._applyFilter();
        }
    };
}

window.magTableFilter = magTableFilter;
