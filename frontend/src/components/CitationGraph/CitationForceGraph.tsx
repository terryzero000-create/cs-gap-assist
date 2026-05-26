import { useEffect, useRef } from 'react';
import * as d3 from 'd3';

interface CitationNode extends d3.SimulationNodeDatum {
  id: string;
  title: string;
  importance_score: number;
  is_key: boolean;
}

interface CitationLink extends d3.SimulationLinkDatum<CitationNode> {
  source: string | CitationNode;
  target: string | CitationNode;
  relation: string;
}

interface CitationForceGraphProps {
  nodes: CitationNode[];
  links: CitationLink[];
}

export function CitationForceGraph({ nodes, links }: CitationForceGraphProps) {
  const ref = useRef<SVGSVGElement | null>(null);

  useEffect(() => {
    if (!ref.current) {
      return;
    }
    const svg = d3.select(ref.current);
    svg.selectAll('*').remove();
    const simulation = d3.forceSimulation(nodes)
      .force('link', d3.forceLink<CitationNode, CitationLink>(links).id((node) => node.id).distance(90))
      .force('charge', d3.forceManyBody().strength(-180))
      .force('center', d3.forceCenter(320, 220));
    const link = svg.append('g').selectAll('line').data(links).join('line').attr('stroke', '#9a8f70');
    const node = svg.append('g').selectAll('circle').data(nodes).join('circle')
      .attr('r', (item) => item.is_key ? 12 : 8)
      .attr('fill', (item) => item.is_key ? '#b7532b' : '#1d3328');
    node.append('title').text((item) => item.title);
    simulation.on('tick', () => {
      link.attr('x1', (item) => (item.source as CitationNode).x ?? 0)
        .attr('y1', (item) => (item.source as CitationNode).y ?? 0)
        .attr('x2', (item) => (item.target as CitationNode).x ?? 0)
        .attr('y2', (item) => (item.target as CitationNode).y ?? 0);
      node.attr('cx', (item) => item.x ?? 0).attr('cy', (item) => item.y ?? 0);
    });
    return () => {
      simulation.stop();
    };
  }, [nodes, links]);

  return <svg ref={ref} width="640" height="440" role="img" aria-label="Citation evolution graph" />;
}
