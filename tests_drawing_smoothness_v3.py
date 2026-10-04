from pathlib import Path

SRC = Path("static/js/draw.js").read_text(encoding="utf-8")
HTML = Path("templates/index.html").read_text(encoding="utf-8")

def test_pointer_moves_are_animation_frame_coalesced():
    assert 'requestAnimationFrame(()=>{' in SRC
    assert 'pendingMove=localXY(ev)' in SRC

def test_drag_locks_native_chart_interaction():
    assert 'mode:"handle",index:hh.index,origData:JSON.parse(JSON.stringify(d.points))};lockChart(true)' in SRC
    assert 'origData:JSON.parse(JSON.stringify(d.points))};lockChart(true)' in SRC
    assert 'drag=null;downXY=null;lockChart(false)' in SRC

def test_one_point_tools_have_live_hover_preview():
    assert 'tool==="hline" || tool==="vline"' in SRC
    assert 'id:"_hover"' in SRC

def test_new_drawing_asset_is_cache_busted():
    assert "js/draw.js') }}?v=46" in HTML
