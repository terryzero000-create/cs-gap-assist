import { useEffect, useRef } from 'react';
import * as d3 from 'd3';
import type { CitationLink, CitationNode } from '../../types';

interface SimNode extends CitationNode, d3.SimulationNodeDatum {}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  source: string | SimNode;
  target: string | SimNode;
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
      return undefined;
    }
    const svg = d3.select(ref.current);
    svg.selectAll('*').remove();

    const width = 760;
    const height = 460;
    const simNodes: SimNode[] = nodes.map((node) => ({ ...node }));
    const simLinks: SimLink[] = links.map((link) => ({ ...link }));

    if (simNodes.length === 0) {
      svg.append('text')
        .attr('x', width / 2)
        .attr('y', height / 2)
        .attr('text-anchor', 'middle')
        .attr('fill', '#607080')
        .text('暂无图谱数据');
      return undefined;
    }

    const viewport = svg.append('g');
    const linkLayer = viewport.append('g').attr('stroke', '#9aa5b1').attr('stroke-opacity', 0.65);
    const nodeLayer = viewport.append('g');
    const labelLayer = viewport.append('g');

    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.65, 2.8])
      .on('zoom', (event) => {
        viewport.attr('transform', event.transform.toString());
      });
    svg.call(zoom);

    const simulation = d3.forceSimulation(simNodes)
      .force('link', d3.forceLink<SimNode, SimLink>(simLinks).id((node) => node.id).distance(105))
      .force('charge', d3.forceManyBody().strength(simNodes.length > 20 ? -95 : -170))
      .force('collision', d3.forceCollide<SimNode>().radius((node) => (node.is_key ? 24 : 18)))
      .force('center', d3.forceCenter(width / 2, height / 2));

    const graphLinks = linkLayer.selectAll('line')
      .data(simLinks)
      .join('line')
      .attr('stroke-width', 1.6);

    const graphNodes = nodeLayer.selectAll('circle')
      .data(simNodes)
      .join('circle')
      .attr('r', (node) => 7 + node.importance_score * 9)
      .attr('fill', (node) => (node.is_key ? '#b44d30' : '#2f6f83'))
      .attr('stroke', '#ffffff')
      .attr('stroke-width', 1.5);

    graphNodes.append('title').text((node) => `${node.title}${node.year ? ` (${node.year})` : ''}`);

    const labels = labelLayer.selectAll('text')
      .data(simNodes.filter((node) => node.is_key))
      .join('text')
      .attr('font-size', 12)
      .attr('font-weight', 700)
      .attr('fill', '#17212b')
      .text((node) => node.title.length > 34 ? `${node.title.slice(0, 31)}...` : node.title);

    simulation.on('tick', () => {
      graphLinks
        .attr('x1', (link) => (link.source as SimNode).x ?? 0)
        .attr('y1', (link) => (link.source as SimNode).y ?? 0)
        .attr('x2', (link) => (link.target as SimNode).x ?? 0)
        .attr('y2', (link) => (link.target as SimNode).y ?? 0);
      graphNodes
        .attr('cx', (node) => node.x ?? 0)
        .attr('cy', (node) => node.y ?? 0);
      labels
        .attr('x', (node) => (node.x ?? 0) + 14)
        .attr('y', (node) => (node.y ?? 0) + 4);
    });

    return () => {
      simulation.stop();
    };
  }, [nodes, links]);

  return <svg ref={ref} className="citation-graph" viewBox="0 0 760 460" role="img" aria-label="引用演化图谱" />;
}
