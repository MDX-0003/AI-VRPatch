// vrpatch pick: ~50 lines, zero npm. ERP click -> fx/fy; inner drag -> rect POST on release.
function markClick(form) {
  var img = form.querySelector('input[type=image]');
  var r = img.getBoundingClientRect();
  form.querySelector('#fx').value = (event.clientX - r.left) / r.width;
  form.querySelector('#fy').value = (event.clientY - r.top) / r.height;
  return true; // submit
}

(function () {
  var wrap = document.getElementById('vpWrap');
  var img = document.getElementById('vpImg');
  var box = document.getElementById('innerBox');
  var form = document.getElementById('innerForm');
  var drag = null;

  function pt(e) {
    var r = img.getBoundingClientRect();
    return { x: (e.clientX - r.left) / r.width * img.naturalWidth,
             y: (e.clientY - r.top) / r.height * img.naturalHeight,
             rx: e.clientX - r.left, ry: e.clientY - r.top };
  }

  img.addEventListener('mousedown', function (e) {
    drag = { a: pt(e) };
    box.style.display = 'block';
    e.preventDefault();
  });
  wrap.addEventListener('mousemove', function (e) {
    if (!drag) return;
    drag.b = pt(e);
    var x = Math.min(drag.a.rx, e.clientX), y = Math.min(drag.a.ry, e.clientY);
    var w = Math.abs(e.clientX - drag.a.rx), h = Math.abs(e.clientY - drag.a.ry);
    var r = img.getBoundingClientRect(), wr = wrap.getBoundingClientRect();
    box.style.left = (x - img.offsetLeft) + 'px';
    box.style.top = (y - img.offsetTop) + 'px';
    box.style.width = w + 'px';
    box.style.height = h + 'px';
  });
  window.addEventListener('mouseup', function (e) {
    if (!drag) return;
    if (drag.b) {
      form.querySelector('[name=x]').value = Math.round(Math.min(drag.a.x, drag.b.x));
      form.querySelector('[name=y]').value = Math.round(Math.min(drag.a.y, drag.b.y));
      form.querySelector('[name=w]').value = Math.round(Math.abs(drag.a.x - drag.b.x));
      form.querySelector('[name=h]').value = Math.round(Math.abs(drag.a.y - drag.b.y));
      form.submit(); // drag finished -> single POST
    }
    drag = null;
  });
})();
