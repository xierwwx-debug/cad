import io
import math
import unittest
import xml.etree.ElementTree as ET
import ezdxf
from ezdxf.math import Vec3
from server import render, split_corners

class GeometryTests(unittest.TestCase):
    def test_closed_rectangle_has_four_segments(self):
        pts=list(map(Vec3,[(0,0),(10,0),(10,10),(0,10),(0,0)]))
        self.assertEqual(len(split_corners(pts)),4)
    def test_smooth_arc_is_not_fragmented(self):
        pts=[Vec3(math.cos(t/100),math.sin(t/100)) for t in range(158)]
        self.assertEqual(len(split_corners(pts)),1)
    def test_line_and_arc_lengths(self):
        doc=ezdxf.new('R2010');doc.units=4
        doc.modelspace().add_line((0,0),(3,4))
        doc.modelspace().add_arc((10,10),2,0,90)
        doc.modelspace().add_text('中文标注')
        stream=io.StringIO();doc.write(stream)
        result=render(stream.getvalue().encode('utf-8'))
        lengths=[float(e.get('data-length')) for e in ET.fromstring(result['svg']).iter() if e.get('class')=='measure-line']
        self.assertAlmostEqual(lengths[0],5)
        self.assertAlmostEqual(lengths[1],math.pi)
        self.assertIn('中文标注',result['svg'])
    def test_invalid_threshold(self):
        with self.assertRaises(ValueError):render(b'',corner_angle=0)
