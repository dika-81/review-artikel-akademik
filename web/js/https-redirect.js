// Pastikan halaman dibuka lewat HTTPS agar API key tidak diketik di halaman
// tanpa enkripsi. Domain kustom GitHub Pages tidak selalu mengalihkan otomatis.
(function () {
  var local = /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname);
  if (location.protocol === "http:" && !local) {
    location.replace("https:" + location.href.slice(location.protocol.length));
  }
})();
