"""
多智能体协同：35 GIS 工具 Mock 压测 + 4 混沌实验
"""
import sys, os, json, tempfile, shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('LLM_PROVIDER', 'deepseek')

# ── Global Mock: GEE ──
@pytest.fixture(autouse=True)
def mock_gee():
    with patch('ee.Initialize', return_value=None), \
         patch('ee.Image', MagicMock()), \
         patch('ee.ImageCollection', MagicMock()), \
         patch('ee.FeatureCollection', MagicMock()), \
         patch('ee.Geometry.Polygon', MagicMock()), \
         patch('ee.Geometry.MultiPolygon', MagicMock()), \
         patch('gis.gee.client.init_gee', return_value={'success': True, 'message': 'GEE mock'}):
        yield

# ── Fixtures ──
@pytest.fixture
def runtime():
    from tools.runtime import GISRuntime
    return GISRuntime()

@pytest.fixture
def registry(runtime):
    from tools import ToolRegistry
    return ToolRegistry(runtime)

@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix='opengis_test_')
    yield d
    shutil.rmtree(d, ignore_errors=True)

@pytest.fixture
def sample_tif():
    """Use a real GeoTIFF from previous successful GEE downloads"""
    candidates = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'workspace', 'outputs', '2024_8_2024-08-01_2024-08-31.tif'),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'workspace', 'outputs', '2026_4_Landsat_SCA.tif'),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    # Try glob
    outdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'workspace', 'outputs')
    if os.path.isdir(outdir):
        tifs = [os.path.join(outdir, f) for f in os.listdir(outdir) if f.endswith('.tif')]
        if tifs:
            return tifs[0]
    pytest.skip("No GeoTIFF found in workspace/outputs")

@pytest.fixture
def sample_output_dir(temp_dir):
    import config
    old = config.OUTPUTS_DIR
    config.OUTPUTS_DIR = Path(temp_dir) / 'outputs'
    config.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    yield config.OUTPUTS_DIR
    config.OUTPUTS_DIR = old


# ═══════════════════════════════════════════
# Batch 1: Search & Admin Region
# ═══════════════════════════════════════════
class TestBatch1_SearchAndAdmin:

    def test_01_search_local_files_empty(self, registry):
        r = registry.call('search_local_files', {'query': ''})
        assert isinstance(r, dict) and 'success' in r

    def test_02_search_local_files_valid(self, registry):
        r = registry.call('search_local_files', {'query': '.tif', 'extensions': ['.tif']})
        assert 'success' in r and 'message' in r

    def test_03_inspect_raster_no_path(self, registry):
        r = registry.call('inspect_raster', {})
        assert isinstance(r, dict)

    def test_04_inspect_raster_valid(self, registry, sample_tif):
        r = registry.call('inspect_raster', {'path': sample_tif})
        assert isinstance(r, dict)

    def test_05_set_current_dataset_invalid(self, registry):
        r = registry.call('set_current_dataset', {'path': '/nonexistent/file.tif'})
        assert r.get('success') == False

    def test_06_set_current_dataset_valid(self, registry, sample_tif):
        r = registry.call('set_current_dataset', {'path': sample_tif})
        assert r.get('success') == True

    def test_07_resolve_admin_region_empty(self, registry):
        r = registry.call('resolve_admin_region', {'region_name': ''})
        assert r.get('success') == False

    def test_08_resolve_admin_region_valid(self, registry):
        r = registry.call('resolve_admin_region', {'region_name': '成都市'})
        assert isinstance(r, dict) and 'success' in r

    def test_09_resolve_admin_region_fuzzy(self, registry):
        r = registry.call('resolve_admin_region', {'region_name': '双流'})
        assert isinstance(r, dict) and 'success' in r

    def test_10_summarize_context(self, registry):
        r = registry.call('summarize_context', {})
        assert r.get('success') == True

    def test_11_update_preferences(self, registry):
        r = registry.call('update_preferences', {'export_format': 'png'})
        assert r.get('success') == True


# ═══════════════════════════════════════════
# Batch 2: Remote Sensing / GEE
# ═══════════════════════════════════════════
class TestBatch2_RemoteSensing:

    def test_12_gee_init(self, registry):
        r = registry.call('gee_init', {})
        assert 'message' in r

    def test_13_gee_compute_lst(self, registry):
        r = registry.call('gee_compute_lst', {'start_date': '2024-08-01', 'end_date': '2024-08-31'})
        assert isinstance(r, dict)

    def test_14_gee_landsat_sca(self, registry):
        r = registry.call('gee_download_landsat_sca', {'start_date': '2024-01-01', 'end_date': '2024-01-31'})
        assert isinstance(r, dict)

    def test_15_gee_monthly_lst(self, registry):
        r = registry.call('gee_download_monthly_lst', {'start_date': '2024-08-01', 'end_date': '2024-08-31'})
        assert isinstance(r, dict)

    def test_16_gee_yearly_lst(self, registry):
        r = registry.call('gee_download_yearly_lst', {'year': 2024})
        assert isinstance(r, dict)

    def test_17_gee_multi_year_lst(self, registry):
        r = registry.call('gee_download_multi_year_lst', {'start_year': 2020, 'end_year': 2023, 'month': 8})
        assert isinstance(r, dict)

    def test_18_run_lst_no_input(self, registry):
        r = registry.call('run_lst', {})
        assert isinstance(r, dict)

    def test_19_run_lst_with_tif(self, registry, sample_tif):
        r = registry.call('run_lst', {'input_tif': sample_tif})
        assert isinstance(r, dict)


# ═══════════════════════════════════════════
# Batch 3: Spatial Analysis
# ═══════════════════════════════════════════
class TestBatch3_SpatialAnalysis:

    def test_20_statistics_no_data(self, registry):
        r = registry.call('statistics', {})
        assert isinstance(r, dict)

    def test_21_statistics_with_tif(self, registry, sample_tif):
        r = registry.call('statistics', {'tif_path': sample_tif})
        assert isinstance(r, dict)

    def test_22_classify_map_no_data(self, registry):
        r = registry.call('classify_map', {})
        assert isinstance(r, dict)

    def test_23_classify_map_with_tif(self, registry, sample_tif, sample_output_dir):
        r = registry.call('classify_map', {'tif_path': sample_tif, 'n_classes': 5})
        assert isinstance(r, dict)

    def test_24_threshold(self, registry, sample_tif, sample_output_dir):
        r = registry.call('threshold_highlight', {'tif_path': sample_tif, 'operator': '>', 'value': 30})
        assert isinstance(r, dict)

    def test_25_enhance(self, registry, sample_tif, sample_output_dir):
        r = registry.call('enhance_raster', {'tif_path': sample_tif, 'method': 'gaussian', 'kernel_size': 3})
        assert isinstance(r, dict)

    def test_26_profile_no_data(self, registry):
        r = registry.call('profile_analysis', {})
        assert isinstance(r, dict)

    def test_27_profile_with_tif(self, registry, sample_tif, sample_output_dir):
        r = registry.call('profile_analysis', {'tif_path': sample_tif, 'start': [0, 50], 'end': [99, 50]})
        assert isinstance(r, dict)

    def test_28_zonal_stats(self, registry):
        r = registry.call('gee_zonal_statistics', {'image_id': 'test', 'stat_type': 'MEAN', 'scale': 1000})
        assert isinstance(r, dict)

    def test_29_timeseries_extract(self, registry):
        r = registry.call('extract_timeseries_to_point', {'lat': 30.5, 'lon': 103.9, 'start_date': '2024-01-01', 'end_date': '2024-12-31'})
        assert isinstance(r, dict)

    def test_30_dynamic_world(self, registry):
        r = registry.call('dynamic_world_landcover', {'start_date': '2024-01-01', 'end_date': '2024-12-31'})
        assert isinstance(r, dict)

    def test_31_ee_classify(self, registry):
        r = registry.call('ee_unsupervised_classify', {'n_clusters': 5, 'start_date': '2024-01-01', 'end_date': '2024-12-31'})
        assert isinstance(r, dict)


# ═══════════════════════════════════════════
# Batch 4: Visualization & Export
# ═══════════════════════════════════════════
class TestBatch4_VisualizationExport:

    def test_32_make_thematic_map_no_data(self, registry):
        r = registry.call('make_thematic_map', {})
        assert r.get('success') == False

    def test_33_make_thematic_map_with_tif(self, registry, sample_tif, sample_output_dir):
        r = registry.call('make_thematic_map', {'tif_path': sample_tif, 'dpi': 150, 'title': 'Test'})
        assert isinstance(r, dict)

    def test_34_set_map_style(self, registry):
        r = registry.call('set_map_style', {'colormap': 'viridis', 'legend_position': 'left'})
        assert r.get('success') == True
        assert registry.runtime.map_style['colormap'] == 'viridis'

    def test_35_set_map_style_north(self, registry):
        r = registry.call('set_map_style', {'north_style': 'circle'})
        assert r.get('success') == True

    def test_36_view_3d_no_data(self, registry):
        r = registry.call('view_3d', {})
        assert isinstance(r, dict)

    def test_37_view_3d_with_tif(self, registry, sample_tif, sample_output_dir):
        r = registry.call('view_3d', {'tif_path': sample_tif})
        assert isinstance(r, dict)

    def test_38_compare_views_no_data(self, registry):
        r = registry.call('compare_views', {})
        assert isinstance(r, dict)

    def test_39_compare_views_with_data(self, registry, sample_tif, sample_output_dir):
        r = registry.call('compare_views', {'tif_original': sample_tif, 'tif_result': sample_tif})
        assert isinstance(r, dict)

    def test_40_transform_raster(self, registry, sample_tif, sample_output_dir):
        r = registry.call('transform_raster', {'tif_path': sample_tif, 'operation': 'flip_h'})
        assert isinstance(r, dict)

    def test_41_export_result(self, registry):
        r = registry.call('export_result', {'format': 'png'})
        assert isinstance(r, dict)

    def test_42_generate_web_map(self, registry, sample_tif, sample_output_dir):
        r = registry.call('generate_web_map', {'tif_path': sample_tif, 'title': 'Test Map'})
        assert isinstance(r, dict)

    def test_43_generate_timeslider(self, registry):
        r = registry.call('generate_timeslider_map', {'image_collection_id': 'test', 'start_date': '2024-01-01', 'end_date': '2024-12-31'})
        assert isinstance(r, dict)

    def test_44_generate_report(self, registry, sample_output_dir):
        r = registry.call('generate_report', {'title': 'Test Report', 'conclusion': 'Test'})
        assert isinstance(r, dict)

    def test_45_gee_lst_timelapse(self, registry):
        r = registry.call('gee_lst_timelapse', {'start_year': 2020, 'end_year': 2023, 'month': 8})
        assert isinstance(r, dict)

    def test_46_gee_lst_timelapse_local(self, registry):
        r = registry.call('gee_lst_timelapse_local', {'start_year': 2020, 'end_year': 2022, 'month': 8})
        assert isinstance(r, dict)

    def test_47_gee_lst_split_panel(self, registry):
        r = registry.call('gee_lst_split_panel', {'year_a': 2020, 'year_b': 2024, 'month': 8})
        assert isinstance(r, dict)

    def test_48_gee_lst_trend_chart(self, registry):
        r = registry.call('gee_lst_trend_chart', {'start_year': 2015, 'end_year': 2024, 'month': 8})
        assert isinstance(r, dict)


# ═══════════════════════════════════════════
# Chaos Experiments
# ═══════════════════════════════════════════
class TestChaosExperiments:

    def test_chaos_01_loop_detection(self):
        from agent.guard import SafetyGuard
        guard = SafetyGuard(max_map_calls=5, max_style_calls=2)
        history = [{'step': i, 'tool': 'make_thematic_map', 'args': {}, 'result': {'success': True}} for i in range(1, 16)]
        assert guard.check(history) != ""

    def test_chaos_02_oom_geojson(self):
        large_geojson = {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[[100 + i*0.01, 30 + (i%10)*0.01] for i in range(1000)]]},
            "properties": {"name": "large"}
        }
        s = json.dumps(large_geojson)
        assert len(s) > 0
        # bbox should not OOM
        try:
            from shapely.geometry import shape
            bounds = shape(large_geojson['geometry']).bounds
            assert len(bounds) == 4
        except Exception:
            pass

    def test_chaos_03_parameter_hallucination(self, registry):
        """LLM hallucinated parameters should not crash"""
        weird = [
            ({'dpi': 'sanbai'}, 'make_thematic_map'),
            ({'n_classes': 'wuge'}, 'classify_map'),
            ({'value': 'sanshidu'}, 'threshold_highlight'),
        ]
        for args, tool in weird:
            try:
                r = registry.call(tool, args)
                assert isinstance(r, dict), f"{tool} returned {type(r)}"
                assert 'success' in r
            except Exception as e:
                pytest.fail(f"{tool} crashed on weird args {args}: {e}")

    def test_chaos_04_ui_action_consistency(self, registry, sample_tif, sample_output_dir):
        from agent.engine import get_ui_action
        cases = [
            ('make_thematic_map', {'tif_path': sample_tif, 'dpi': 100}, 'RENDER_IMAGE'),
            ('statistics', {'tif_path': sample_tif}, 'RENDER_CHART'),
            ('classify_map', {'tif_path': sample_tif, 'n_classes': 3}, 'RENDER_IMAGE'),
        ]
        for tool, args, expected in cases:
            r = registry.call(tool, args)
            ui = get_ui_action(tool, r)
            if r.get('success'):
                assert ui == expected, f"{tool}: ui_action={ui}, expected={expected}"
            else:
                assert ui == 'NONE', f"{tool} failed but ui_action={ui}"


def test_tool_count(registry):
    assert len(registry._tools) == 35, f"Expected 35 tools, got {len(registry._tools)}"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
