export type FooterAgentKind = 'claude' | 'codex' | 'antigravity';

interface FooterAgentLogoProps {
  kind: FooterAgentKind;
  className?: string;
}

const CLAUDE_PATH =
  'm4.7144 15.9555 4.7174-2.6471.079-.2307-.079-.1275h-.2307l-.7893-.0486-2.6956-.0729-2.3375-.0971-2.2646-.1214-.5707-.1215-.5343-.7042.0546-.3522.4797-.3218.686.0608 1.5179.1032 2.2767.1578 1.6514.0972 2.4468.255h.3886l.0546-.1579-.1336-.0971-.1032-.0972L6.973 9.8356l-2.55-1.6879-1.3356-.9714-.7225-.4918-.3643-.4614-.1578-1.0078.6557-.7225.8803.0607.2246.0607.8925.686 1.9064 1.4754 2.4893 1.8336.3643.3035.1457-.1032.0182-.0728-.164-.2733-1.3539-2.4467-1.445-2.4893-.6435-1.032-.17-.6194c-.0607-.255-.1032-.4674-.1032-.7285L6.287.1335 6.6997 0l.9957.1336.419.3642.6192 1.4147 1.0018 2.2282 1.5543 3.0296.4553.8985.2429.8318.091.255h.1579v-.1457l.1275-1.706.2368-2.0947.2307-2.6957.0789-.7589.3764-.9107.7468-.4918.5828.2793.4797.686-.0668.4433-.2853 1.8517-.5586 2.9021-.3643 1.9429h.2125l.2429-.2429.9835-1.3053 1.6514-2.0643.7286-.8196.85-.9046.5464-.4311h1.0321l.759 1.1293-.34 1.1657-1.0625 1.3478-.8804 1.1414-1.2628 1.7-.7893 1.36.0729.1093.1882-.0183 2.8535-.607 1.5421-.2794 1.8396-.3157.8318.3886.091.3946-.3278.8075-1.967.4857-2.3072.4614-3.4364.8136-.0425.0304.0486.0607 1.5482.1457.6618.0364h1.621l3.0175.2247.7892.522.4736.6376-.079.4857-1.2142.6193-1.6393-.3886-3.825-.9107-1.3113-.3279h-.1822v.1093l1.0929 1.0686 2.0035 1.8092 2.5075 2.3314.1275.5768-.3218.4554-.34-.0486-2.2039-1.6575-.85-.7468-1.9246-1.621h-.1275v.17l.4432.6496 2.3436 3.5214.1214 1.0807-.17.3521-.6071.2125-.6679-.1214-1.3721-1.9246L14.38 17.959l-1.1414-1.9428-.1397.079-.674 7.2552-.3156.3703-.7286.2793-.6071-.4614-.3218-.7468.3218-1.4753.3886-1.9246.3157-1.53.2853-1.9004.17-.6314-.0121-.0425-.1397.0182-1.4328 1.9672-2.1796 2.9446-1.7243 1.8456-.4128.164-.7164-.3704.0667-.6618.4008-.5889 2.386-3.0357 1.4389-1.882.929-1.0868-.0062-.1579h-.0546l-6.3385 4.1164-1.1293.1457-.4857-.4554.0608-.7467.2307-.2429 1.9064-1.3114Z';

const CODEX_PATH =
  'M8.086.457a6.105 6.105 0 013.046-.415c1.333.153 2.521.72 3.564 1.7a.117.117 0 00.107.029c1.408-.346 2.762-.224 4.061.366l.063.03.154.076c1.357.703 2.33 1.77 2.918 3.198.278.679.418 1.388.421 2.126a5.655 5.655 0 01-.18 1.631.167.167 0 00.04.155 5.982 5.982 0 011.578 2.891c.385 1.901-.01 3.615-1.183 5.14l-.182.22a6.063 6.063 0 01-2.934 1.851.162.162 0 00-.108.102c-.255.736-.511 1.364-.987 1.992-1.199 1.582-2.962 2.462-4.948 2.451-1.583-.008-2.986-.587-4.21-1.736a.145.145 0 00-.14-.032c-.518.167-1.04.191-1.604.185a5.924 5.924 0 01-2.595-.622 6.058 6.058 0 01-2.146-1.781c-.203-.269-.404-.522-.551-.821a7.74 7.74 0 01-.495-1.283 6.11 6.11 0 01-.017-3.064.166.166 0 00.008-.074.115.115 0 00-.037-.064 5.958 5.958 0 01-1.38-2.202 5.196 5.196 0 01-.333-1.589 6.915 6.915 0 01.188-2.132c.45-1.484 1.309-2.648 2.577-3.493.282-.188.55-.334.802-.438.286-.12.573-.22.861-.304a.129.129 0 00.087-.087A6.016 6.016 0 015.635 2.31C6.315 1.464 7.132.846 8.086.457zm-.804 7.85a.848.848 0 00-1.473.842l1.694 2.965-1.688 2.848a.849.849 0 001.46.864l1.94-3.272a.849.849 0 00.007-.854l-1.94-3.393zm5.446 6.24a.849.849 0 000 1.695h4.848a.849.849 0 000-1.696h-4.848z';

const ANTIGRAVITY_ARCH_PATH =
  'M14.0777 13.984C14.945 14.6345 16.2458 14.2008 15.0533 13.0084C11.476 9.53949 12.2349 0 7.79033 0C3.34579 0 4.10461 9.53949 0.527295 13.0084C-0.773543 14.3092 0.635692 14.6345 1.50293 13.984C4.86344 11.7076 4.64663 7.69664 7.79033 7.69664C10.934 7.69664 10.7172 11.7076 14.0777 13.984Z';

export default function FooterAgentLogo({ kind, className }: FooterAgentLogoProps) {
  if (kind === 'claude') {
    return (
      <svg
        className={className}
        viewBox="0 0 24 24"
        fill="#D97757"
        aria-hidden="true"
        focusable="false"
      >
        <path d={CLAUDE_PATH} />
      </svg>
    );
  }

  if (kind === 'codex') {
    return (
      <svg
        className={className}
        viewBox="0 0 24 24"
        fill="#f4f4f5"
        fillRule="evenodd"
        clipRule="evenodd"
        aria-hidden="true"
        focusable="false"
      >
        <path d={CODEX_PATH} />
      </svg>
    );
  }

  return (
    <svg
      className={className}
      viewBox="0 0 16 15"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <clipPath id="sh-ag-clip">
          <path d={ANTIGRAVITY_ARCH_PATH} />
        </clipPath>
        <filter
          id="sh-ag-f0"
          x="-2.12817"
          y="-8.35998"
          width="12.8393"
          height="11.383"
          filterUnits="userSpaceOnUse"
          colorInterpolationFilters="sRGB"
        >
          <feFlood floodOpacity="0" result="BackgroundImageFix" />
          <feBlend mode="normal" in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
          <feGaussianBlur stdDeviation="0.722959" result="effect1" />
        </filter>
        <filter
          id="sh-ag-f1"
          x="2.75168"
          y="-9.38089"
          width="25.1763"
          height="24.96"
          filterUnits="userSpaceOnUse"
          colorInterpolationFilters="sRGB"
        >
          <feFlood floodOpacity="0" result="BackgroundImageFix" />
          <feBlend mode="normal" in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
          <feGaussianBlur stdDeviation="3.49513" result="effect1" />
        </filter>
        <filter
          id="sh-ag-f2"
          x="-14.1669"
          y="-7.50196"
          width="26.5068"
          height="23.6338"
          filterUnits="userSpaceOnUse"
          colorInterpolationFilters="sRGB"
        >
          <feFlood floodOpacity="0" result="BackgroundImageFix" />
          <feBlend mode="normal" in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
          <feGaussianBlur stdDeviation="2.97119" result="effect1" />
        </filter>
        <filter
          id="sh-ag-f4"
          x="-12.3607"
          y="-7.29981"
          width="23.709"
          height="23.6846"
          filterUnits="userSpaceOnUse"
          colorInterpolationFilters="sRGB"
        >
          <feFlood floodOpacity="0" result="BackgroundImageFix" />
          <feBlend mode="normal" in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
          <feGaussianBlur stdDeviation="2.97119" result="effect1" />
        </filter>
        <filter
          id="sh-ag-f5"
          x="0.634962"
          y="5.02095"
          width="21.7027"
          height="22.0616"
          filterUnits="userSpaceOnUse"
          colorInterpolationFilters="sRGB"
        >
          <feFlood floodOpacity="0" result="BackgroundImageFix" />
          <feBlend mode="normal" in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
          <feGaussianBlur stdDeviation="2.82351" result="effect1" />
        </filter>
        <filter
          id="sh-ag-f6"
          x="-3.97547"
          y="-14.6666"
          width="23.2857"
          height="22.8313"
          filterUnits="userSpaceOnUse"
          colorInterpolationFilters="sRGB"
        >
          <feFlood floodOpacity="0" result="BackgroundImageFix" />
          <feBlend mode="normal" in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
          <feGaussianBlur stdDeviation="2.5589" result="effect1" />
        </filter>
        <filter
          id="sh-ag-f7"
          x="-7.7407"
          y="-0.945408"
          width="29.1982"
          height="30.1105"
          filterUnits="userSpaceOnUse"
          colorInterpolationFilters="sRGB"
        >
          <feFlood floodOpacity="0" result="BackgroundImageFix" />
          <feBlend mode="normal" in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
          <feGaussianBlur stdDeviation="2.2852" result="effect1" />
        </filter>
        <filter
          id="sh-ag-f8"
          x="6.78641"
          y="-0.27231"
          width="16.2415"
          height="15.5681"
          filterUnits="userSpaceOnUse"
          colorInterpolationFilters="sRGB"
        >
          <feFlood floodOpacity="0" result="BackgroundImageFix" />
          <feBlend mode="normal" in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
          <feGaussianBlur stdDeviation="2.04485" result="effect1" />
        </filter>
        <filter
          id="sh-ag-f9"
          x="3.77526"
          y="-8.71693"
          width="21.687"
          height="19.4212"
          filterUnits="userSpaceOnUse"
          colorInterpolationFilters="sRGB"
        >
          <feFlood floodOpacity="0" result="BackgroundImageFix" />
          <feBlend mode="normal" in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
          <feGaussianBlur stdDeviation="1.72712" result="effect1" />
        </filter>
        <filter
          id="sh-ag-f10"
          x="-5.40727"
          y="-6.39238"
          width="14.3639"
          height="16.9254"
          filterUnits="userSpaceOnUse"
          colorInterpolationFilters="sRGB"
        >
          <feFlood floodOpacity="0" result="BackgroundImageFix" />
          <feBlend mode="normal" in="SourceGraphic" in2="BackgroundImageFix" result="shape" />
          <feGaussianBlur stdDeviation="2.1376" result="effect1" />
        </filter>
      </defs>
      <g clipPath="url(#sh-ag-clip)">
        <path d={ANTIGRAVITY_ARCH_PATH} fill="#3186FF" />
        <g filter="url(#sh-ag-f0)">
          <path
            d="M-0.658907 -3.2306C-0.922679 -0.906781 1.07986 1.22861 3.81388 1.53894C6.54791 1.84927 8.97811 0.217009 9.24188 -2.10681C9.50565 -4.43063 7.50312 -6.56602 4.76909 -6.87635C2.03506 -7.18667 -0.395135 -5.55442 -0.658907 -3.2306Z"
            fill="#FFE432"
          />
        </g>
        <g filter="url(#sh-ag-f1)">
          <path
            d="M9.88233 4.36642C10.5673 7.31568 13.566 9.13902 16.5801 8.43896C19.5942 7.73891 21.4823 4.78056 20.7973 1.83131C20.1123 -1.11795 17.1136 -2.94128 14.0995 -2.24123C11.0854 -1.54118 9.19733 1.41717 9.88233 4.36642Z"
            fill="#FC413D"
          />
        </g>
        <g filter="url(#sh-ag-f2)">
          <path
            d="M-8.05291 6.34512C-7.18736 9.38883 -3.28925 10.9473 0.653774 9.82598C4.5968 8.7047 7.09158 5.32829 6.22603 2.28458C5.36048 -0.759142 1.46236 -2.31758 -2.48066 -1.19629C-6.42368 -0.0750048 -8.91846 3.3014 -8.05291 6.34512Z"
            fill="#00B95C"
          />
        </g>
        <g filter="url(#sh-ag-f4)">
          <path
            d="M-4.92402 8.86746C-2.75421 11.0837 0.982691 10.9438 3.42257 8.55507C5.86246 6.1663 6.08139 2.43321 3.91158 0.216963C1.74177 -1.99928 -1.99513 -1.85942 -4.43501 0.529349C-6.87489 2.91812 -7.09383 6.65122 -4.92402 8.86746Z"
            fill="#00B95C"
          />
        </g>
        <g filter="url(#sh-ag-f5)">
          <path
            d="M6.42819 17.2263C7.10197 20.1273 9.91278 21.953 12.7063 21.3042C15.4998 20.6553 17.2182 17.7777 16.5444 14.8767C15.8707 11.9757 13.0599 10.15 10.2663 10.7988C7.47281 11.4477 5.75441 14.3253 6.42819 17.2263Z"
            fill="#3186FF"
          />
        </g>
        <g filter="url(#sh-ag-f6)">
          <path
            d="M1.66508 -5.94539C0.254213 -2.80254 1.7978 0.951609 5.11277 2.43973C8.42774 3.92785 12.2588 2.58642 13.6696 -0.556431C15.0805 -3.69928 13.5369 -7.45343 10.222 -8.94155C6.90699 -10.4297 3.07594 -9.08824 1.66508 -5.94539Z"
            fill="#FBBC04"
          />
        </g>
        <g filter="url(#sh-ag-f7)">
          <path
            d="M-2.11428 24.3903C-5.52984 23.0496 0.307266 12.0177 1.75874 8.32038C3.21024 4.62304 7.15576 2.71272 10.5713 4.05357C13.9869 5.39442 18.0354 12.7796 16.5838 16.477C15.1323 20.1743 1.30129 25.7311 -2.11428 24.3903Z"
            fill="#3186FF"
          />
        </g>
        <g filter="url(#sh-ag-f8)">
          <path
            d="M18.5814 10.6598C17.6669 11.727 15.2806 11.1828 13.2514 9.44417C11.2222 7.70556 10.3185 5.43097 11.2329 4.3637C12.1473 3.29646 14.5336 3.84069 16.5628 5.57928C18.592 7.31789 19.4958 9.59249 18.5814 10.6598Z"
            fill="#749BFF"
          />
        </g>
        <g filter="url(#sh-ag-f9)">
          <path
            d="M11.7552 5.22715C15.5162 7.77124 19.8471 7.93838 21.4286 5.60045C23.0101 3.26253 21.2433 -0.695128 17.4823 -3.23922C13.7213 -5.78331 9.39044 -5.95044 7.80896 -3.61252C6.22747 -1.27459 7.99428 2.68306 11.7552 5.22715Z"
            fill="#FC413D"
          />
        </g>
        <g filter="url(#sh-ag-f10)">
          <path
            d="M-0.592149 1.08896C-1.5239 3.33663 -1.21959 5.59799 0.0875457 6.13985C1.39468 6.68171 3.20966 5.29888 4.14141 3.05121C5.07316 0.803541 4.76885 -1.45782 3.46171 -1.99968C2.15458 -2.54154 0.339602 -1.15871 -0.592149 1.08896Z"
            fill="#FFEE48"
          />
        </g>
      </g>
    </svg>
  );
}
