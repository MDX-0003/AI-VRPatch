// vrpatch pick: ~50 lines, zero npm. ERP click -> fx/fy; inner drag -> rect POST on release.
// Coordinates: everything displayed AND submitted derives from pt() (image-relative),
// so the live dashed box always sits under the cursor and matches the committed rect.
function markClick(form) {
  var img = form.querySelector('input[type=image]');
  var r = img.getBoundingClientRect();
  form.querySelector('#fx').value = (event.clientX - r.left) / r.width;
  form.querySelector('#fy').value = (event.clientY - r.top) / r.height;
  return true; // submit
}

(function () {
  var img = document.getElementById('vpImg');
  var box = document.getElementById('innerBox');
  var form = document.getElementById('innerForm');
  var drag = null;

  // one true mapping: browser event -> image-relative coords (display px and natural px)
  function pt(e) {
    var r = img.getBoundingClientRect();
    return { rx: e.clientX - r.left, ry: e.clientY - r.top,
             x: (e.clientX - r.left) / r.width * img.naturalWidth,
             y: (e.clientY - r.top) / r.height * img.naturalHeight };
  }

  img.addEventListener('mousedown', function (e) {
    drag = { a: pt(e) };
    box.style.display = 'block';
    e.preventDefault();
  });
  img.addEventListener('mousemove', function (e) {
    if (!drag) return;
    var b = pt(e);
    var x = Math.min(drag.a.rx, b.rx), y = Math.min(drag.a.ry, b.ry);
    box.style.left = x + 'px';
    box.style.top = y + 'px';
    box.style.width = Math.abs(b.rx - drag.a.rx) + 'px';
    box.style.height = Math.abs(b.ry - drag.a.ry) + 'px';
  });
  window.addEventListener('mouseup', function (e) {
    if (!drag) return;
    var b = pt(e);
    var w = Math.abs(b.x - drag.a.x), h = Math.abs(b.y - drag.a.y);
    if (w > 2 && h > 2) {
      form.querySelector('[name=x]').value = Math.round(Math.min(drag.a.x, b.x));
      form.querySelector('[name=y]').value = Math.round(Math.min(drag.a.y, b.y));
      form.querySelector('[name=w]').value = Math.round(w);
      form.querySelector('[name=h]').value = Math.round(h);
      form.submit(); // drag finished -> single POST
    } else {
      box.style.display = 'none'; // click without drag: no-op
    }
    drag = null;
  });
})();
