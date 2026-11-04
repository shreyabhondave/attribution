import { useApi } from '../hooks'
import { num } from '../format'
import { Await } from '../ui'
import type { QualityItem, QualityLevel, QualityResponse } from '../types'
import type { TabProps } from './types'

const TAG: Record<QualityLevel, [string, string]> = { fix: ['Corrected', 'info'], exclude: ['Excluded', 'warn'], info: ['Kept', 'mute'], warn: ['Review', 'bad'] }

const groupBy = (items: QualityItem[]) => items.reduce<Map<string, QualityItem[]>>((m, i) => m.set(i.group, [...(m.get(i.group) ?? []), i]), new Map())

export default function Quality({ version }: TabProps) {
  const quality = useApi<QualityResponse>('/api/quality', {}, version)
  return (
    <>
      <div className="explain">
        The data does not always agree with itself. Everything below was <b>detected automatically</b>, and either corrected or excluded so the numbers can be trusted. Nothing is silently dropped: raw rows stay stored.
      </div>
      <Await state={quality}>
        {({ items }) => [...groupBy(items)].map(([group, list]) => (
          <section key={group}>
            <h3 className="grp">{group}</h3>
            <div className="qgrid">
              {list.map((i) => (
                <article className="q" key={i.title}>
                  <div className="t"><span>{i.title}</span><span className={`badge ${TAG[i.level][1]}`}>{TAG[i.level][0]}</span></div>
                  <div className="c">{num(i.count)}</div>
                  <p>{i.detail}</p>
                  <div className="a"><b>What we did:</b> {i.action}</div>
                </article>
              ))}
            </div>
          </section>
        ))}
      </Await>
    </>
  )
}
